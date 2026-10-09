from __future__ import annotations

import re
import uuid
from urllib.parse import urlsplit

import httpx

from snaplii.config_store import ConfigStore
from snaplii import auth
from snaplii.exceptions import (
    ItemIdError,
    AmountValidationError,
    AuthError,
    ConfigError,
    GatewayApiError,
    GatewayConnectionError,
    SnapliiCliError,
    TransferApiError,
)


_ITEM_ID = re.compile(r"[^\s-]+-[^\s-]+\Z")  # {cardBrandId}-{cardTemplateId}: two parts, one hyphen


def _client_version() -> str:
    try:
        from importlib.metadata import version
        return version("snaplii-cli")
    except Exception:
        return "unknown"


def summarize_denominations(brand_resp: dict) -> list:
    """Extract the real, structured denominations from a brand-detail response.

    Returns one entry per card with its exact type and amount(s) taken straight
    from the gateway's faceValueRules — so the agent uses real min/max values
    instead of guessing. VARIABLE cards expose {min, max}; FIXED expose {amount}.
    """
    brand = brand_resp.get("data", brand_resp) if isinstance(brand_resp, dict) else brand_resp
    if not isinstance(brand, dict):
        return []
    brand_id = brand.get("cardBrandId", "")
    out = []
    for c in brand.get("cards", []) or []:
        if not isinstance(c, dict):
            continue
        fv = c.get("faceValueRules", {}) or {}
        tid = c.get("cardTemplateId", "")
        entry = {
            "item_id": f"{brand_id}-{tid}" if brand_id and tid else tid,
            "type": fv.get("type"),
        }
        if fv.get("type") == "VARIABLE":
            entry["min"] = fv.get("priceStart")
            entry["max"] = fv.get("priceEnd")
        else:
            entry["amount"] = fv.get("priceStart")
        disc = c.get("discount") or c.get("regularDiscount")
        if disc:
            entry["cashback_percent"] = disc
        out.append(entry)
    return out


class GatewayClient:
    def __init__(self, base_url: str, config_store: ConfigStore):
        self._base_url = auth.normalize_base_url(base_url)
        self._origin = auth.normalize_origin(base_url)
        parsed = urlsplit(self._origin)
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1"):
            raise ConfigError("Gateway URL must use HTTPS for non-local connections.")
        # httpx needs httpcore at request time; a partial install raises a cryptic
        # "No module named 'httpcore'". Fail early with an actionable message.
        try:
            import httpcore  # noqa: F401
        except Exception as e:
            raise ConfigError(
                "Missing dependency 'httpcore' (required by httpx). Reinstall the CLI: "
                "pip install -U snaplii-cli (or pip install httpcore). "
                "If you use the ClawHub plugin / a managed MCP connector, restart it so it "
                "re-resolves dependencies."
            ) from e
        self._config = config_store
        self._http = httpx.Client(timeout=30.0, event_hooks={"request": [self._identify]})

    def _identify(self, request: httpx.Request) -> None:
        """Name the official client on every request, e.g. `snaplii-cli/0.19.0 (mcp)`, so the
        gateway can tell CLI and MCP traffic from agents calling the API directly. Telemetry
        only: any caller can send this header, so it must never gate access."""
        request.headers["X-Snaplii-Client"] = "snaplii-cli/%s (%s)" % (
            _client_version(), getattr(self._config, "runtime", None) or "library")

    # ── Auth ──────────────────────────────────────────────────────

    @property
    def origin(self) -> str:
        return self._origin

    def login(self, agent_id: str, api_key: str) -> dict:
        auth.require_login_origin(self._origin)
        resp = self._post("/v2/auth/token", json={
            "agent_id": agent_id,
            "api_key": api_key,
        })
        return self._finish_login(resp, agent_id=agent_id, auth_method="api_key")

    def login_via_vault(self, agent_id: str) -> dict:
        """Exchange a host-managed API key without exposing it to this process.

        The host owns input and cancellation; this method only exchanges an
        existing credential. Opaque lookup failures require native inspection.
        """
        import importlib.util
        import json
        import os
        import sys
        import urllib.error
        import urllib.request
        from pathlib import Path

        origin = auth.validate_vault_origin(self._base_url)
        helper_file = Path(os.environ.get(
            "SNAPLII_VAULT_HELPER_PATH", str(auth.MUSE_HELPER.parent)
        )) / "dynamic_credentials.py"
        module_name = "_snaplii_credentials_" + uuid.uuid4().hex
        try:
            # An explicit file avoids cwd/module-cache substitution, without
            # adding a credential helper directory to the global import path.
            spec = importlib.util.spec_from_file_location(module_name, helper_file)
            if spec is None or spec.loader is None:
                raise ImportError
            helper = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = helper
            spec.loader.exec_module(helper)
        except Exception:
            raise self._auth_error("secure_entry_unavailable", "credential_helper_unavailable",
                                   "The secure credential store helper is unavailable.", "vault") from None
        finally:
            sys.modules.pop(module_name, None)

        url = origin + "/v2/auth/token"
        payload = json.dumps({"agent_id": agent_id}).encode()
        req = urllib.request.Request(url, data=payload, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            helper.add_surrogate_to_request(req, "custom.snaplii",
                                             allowed_hosts=(urlsplit(origin).hostname,))
        except Exception:
            # Do not interpret an opaque exception as "missing key". Muse must
            # distinguish missing/denied/unavailable using its native capability.
            state = "credential_lookup_failed" if self.auth_status()["host"] == "muse" else "secure_entry_unavailable"
            raise self._auth_error(state, "credential_helper_failed",
                                   "The secure credential store could not provide a credential.", "vault") from None
        if req.full_url != url or req.get_method() != "POST" or req.data != payload:
            raise self._auth_error("secure_entry_unavailable", "credential_request_modified",
                                   "The credential request was changed unexpectedly.", "vault")

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirect())
        try:
            with opener.open(req, timeout=30) as response:
                raw = response.read().decode("utf-8", "replace")
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            status = exc.code
        except (urllib.error.URLError, TimeoutError, OSError):
            raise self._auth_error("temporary_gateway_error", "auth_transport_failed",
                                   "Could not reach Snaplii to authenticate. Retry authentication later.", "vault") from None
        if 300 <= status < 400:
            raise self._auth_error("secure_entry_unavailable", "credential_redirect_blocked",
                                   "A redirect was blocked during secure credential authentication.", "vault")
        body = self._parse_login_response(httpx.Response(status, text=raw), "vault")
        return self._finish_login(body, agent_id=agent_id, auth_method="vault")

    def _parse_login_response(self, response, method):
        try:
            return self._parse_response(response, "/v2/auth/token")
        except GatewayApiError as exc:
            code = exc.body.get("rspMsgCd")
            code = code if isinstance(code, str) and code in self._ERROR_MESSAGES else ""
            safe = {"rspMsgCd": code}
            if code:
                safe["friendly_message"] = self._ERROR_MESSAGES[code]
            error = GatewayApiError(exc.status_code, safe, "/v2/auth/token")
            state = ("invalid_key" if exc.status_code in (401, 403) or code.startswith("MCA201")
                     else "temporary_gateway_error" if exc.status_code >= 500 else "auth_response_invalid")
            error.auth_fields = self._auth_fields(state, "auth_gateway_rejected", method)
            raise error from None

    def _finish_login(self, resp: dict, *, agent_id, auth_method: str) -> dict:
        """Shared tail of every login path: validate the token and cache it."""
        body = resp if isinstance(resp, dict) else {}
        token = body.get("access_token")
        if not token:
            error = GatewayApiError(200, {"friendly_message": "Login did not return an access token."}, "/v2/auth/token")
            error.auth_fields = self._auth_fields("auth_response_invalid", "missing_access_token", auth_method)
            raise error
        expires_in = body.get("expires_in", 3600)
        self._config.commit_session(token, expires_in, agent_id=agent_id,
                                    auth_method=auth_method, token_origin=self._origin,
                                    country=body.get("country"))
        if self._config.get_cached_token(origin=self._origin) != token:
            raise self._auth_error("session_cache_failed", "session_readback_failed",
                                   "The session could not be verified. Authentication is incomplete.", auth_method)
        return body

    def accept_connect_token(self, response: dict) -> dict:
        """Commit the URL-elicitation result through the same login boundary."""
        agent_id = response.get("agent_id") if isinstance(response, dict) else None
        return self._finish_login(response, agent_id=agent_id, auth_method="url")

    def auth_status(self) -> dict:
        return self._config.auth_status(origin=self._base_url)

    def _auth_fields(self, state, reason, method=None):
        status = self.auth_status()
        if state == status.get("auth_state") and (method is None or method == status.get("auth_method")):
            # The store already applied its runtime policy (e.g. an MCP process
            # recovers through snaplii_connect, not a separate CLI).
            action = status["next_action"]
        else:
            action = auth.build_auth_action(state, host=status["host"],
                                            auth_method=method or status["auth_method"], origin=self._base_url)
        return {"auth_state": state, "reason_code": reason, "next_action": action}

    def _auth_error(self, state, reason, message, method=None):
        return AuthError(message, **self._auth_fields(state, reason, method))

    def poll_connect_token(self, eid: str) -> dict | None:
        """Take the token the gateway parked under `eid` after the user submitted
        their key on the hosted /connect page (URL-mode elicitation). Sends NO auth
        header — the endpoint is guarded by possession of the one-time eid. Returns
        the token dict on 200, or None when not ready yet (204) / on any other
        status, so the caller can keep polling."""
        auth.require_login_origin(self._origin)
        url = f"{self._base_url}/v2/auth/elicit/{eid}/token"
        try:
            resp = self._http.get(url)
        except httpx.ConnectError as e:
            raise GatewayConnectionError(url, e)
        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                return None
        return None

    # ── User cards ────────────────────────────────────────────────

    def list_user_cards(self, status: str = "ACTIVE", page: int = 1, page_size: int = 20) -> dict:
        return self._get("/v2/cards", params={
            "status": status,
            "page": str(page),
            "pageSize": str(page_size),
        })

    def get_card_detail(self, card_no: str) -> dict:
        return self._get(f"/v2/cards/{card_no}")

    # ── Card browsing ─────────────────────────────────────────────

    def get_all_card_tags(self, channel: str = "HOME_PAGE") -> dict:
        # The account's country is fixed at login and enforced server-side, so
        # the catalog is already scoped to the user — no province/state filter.
        resp = self._get("/v2/card-brands", params={"channel": channel})
        # Gateway returns list directly; normalize to {"data": [...]}
        if isinstance(resp, list):
            return {"data": resp}
        return resp

    def get_card_brand_by_id(self, card_brand_id: str) -> dict:
        resp = self._get(f"/v2/card-brands/{card_brand_id}", params={
            "showDetail": "true",
        })
        # Gateway returns detail directly; normalize to {"data": {...}}
        if isinstance(resp, dict) and "data" not in resp and "cardBrandId" in resp:
            return {"data": resp}
        return resp

    # ── Amount guard ──────────────────────────────────────────────

    def validate_amount(self, item_id: str, price) -> None:
        """Guard quote/purchase: `item_id` must be exactly {cardBrandId}-{cardTemplateId}
        with a template that is a card of that brand, and `price` must fall within
        that card's allowed denomination.

        Raises ItemIdError for a malformed item_id or a template the resolved brand
        does not list, and AmountValidationError when the amount is confirmed out of
        range. Fails open (returns silently) whenever the catalog can't be resolved —
        the server stays the final authority. This mirrors the app's UI check
        (DrawerBottomInputAmount) which the agent path would otherwise bypass.
        """
        if not isinstance(item_id, str) or not _ITEM_ID.match(item_id):
            raise ItemIdError(
                "item_id must be exactly {cardBrandId}-{cardTemplateId}, copied verbatim from "
                "browse brand (e.g. CB00000000000086-CT000000003618); got %r." % (item_id,),
                item_id=item_id if isinstance(item_id, str) else "")
        brand_id, _, template_id = item_id.partition("-")

        try:
            detail = self.get_card_brand_by_id(brand_id)
        except SnapliiCliError:
            return  # catalog fetch failed — don't block; server decides

        brand = detail.get("data", detail) if isinstance(detail, dict) else {}
        cards = brand.get("cards", []) if isinstance(brand, dict) else []
        cards = [c for c in cards or [] if isinstance(c, dict)]
        card = next((c for c in cards if c.get("cardTemplateId") == template_id), None)
        if not card:
            if cards:
                raise ItemIdError(
                    "Template %s is not a card of brand %s, so this item_id would buy a different "
                    "card. Copy item_id verbatim from browse brand." % (template_id, brand_id),
                    item_id=item_id)
            return  # the brand lists no cards to compare against — server decides

        try:
            amount = float(price)
        except (TypeError, ValueError):
            return  # malformed price — let the server reject it

        fv = card.get("faceValueRules", {}) or {}
        ftype = fv.get("type")

        def _num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        if ftype == "FIXED":
            fixed = _num(fv.get("priceStart"))
            if fixed is not None and amount != fixed:
                raise AmountValidationError(
                    f"This card is a fixed ${fixed:g} denomination — "
                    f"${amount:g} is not available. Buy exactly ${fixed:g}.",
                    item_id=item_id, amount=amount, fixed=fixed,
                )
        elif ftype == "VARIABLE":
            lo = _num(fv.get("priceStart"))
            hi = _num(fv.get("priceEnd"))
            if lo is not None and amount < lo:
                raise AmountValidationError(
                    f"${amount:g} is below this card's ${lo:g} minimum. "
                    f"Choose ${lo:g} or more.",
                    item_id=item_id, amount=amount, min_amount=lo, max_amount=hi,
                )
            if hi is not None and amount > hi:
                raise AmountValidationError(
                    f"${amount:g} is above this card's ${hi:g} maximum. "
                    f"For larger amounts, contact Snaplii.",
                    item_id=item_id, amount=amount, min_amount=lo, max_amount=hi,
                )

    # ── Purchase ──────────────────────────────────────────────────

    def create_order_and_pay(
        self,
        item_id: str,
        price: str,
        payment_method: str = "SNAPLII_CREDIT",
        payment_token: str | None = None,
        voucher_option: str = "BEST_FIT",
        cashback_option: str = "USE",
        specified_voucher: str | None = None,
    ) -> dict:
        payment_ctx = {
            "specifiedPrimaryPaymentMethod": payment_method,
            "voucherOption": voucher_option,
            "cashbackOption": cashback_option,
        }
        if specified_voucher:
            payment_ctx["specifiedVoucher"] = specified_voucher
            payment_ctx["voucherOption"] = "USE"   # match billpay_create_and_pay
        if payment_token:
            payment_ctx["specifiedPrimaryPaymentToken"] = payment_token
        return self._post("/v2/purchase", json={
            "orderInfo": {
                "orderType": "GIFT_CARD",
                "item": {"itemId": item_id, "price": price},
                "orderContext": {"giftOrder": "false"},
                "businessChannel": "APP",
            },
            "paymentContext": payment_ctx,
            "delivery": {"type": "WALLET", "immediateSend": "true"},
        })

    # ── Quote ─────────────────────────────────────────────────────

    def quote_order(
        self,
        item_id: str,
        price: str,
        payment_method: str = "SNAPLII_CREDIT",
        payment_token: str | None = None,
        voucher_option: str = "BEST_FIT",
        cashback_option: str = "USE",
        specified_voucher: str | None = None,
    ) -> dict:
        payment_ctx = {
            "specifiedPrimaryPaymentMethod": payment_method,
            "voucherOption": voucher_option,
            "cashbackOption": cashback_option,
        }
        if payment_token:
            payment_ctx["specifiedPrimaryPaymentToken"] = payment_token
        if specified_voucher:
            payment_ctx["specifiedVoucher"] = specified_voucher
        return self._post("/v2/quote", json={
            "orderInfo": {
                "orderType": "GIFT_CARD",
                "item": {"itemId": item_id, "price": price},
                "orderContext": {"giftOrder": "false"},
                "businessChannel": "APP",
            },
            "paymentContext": payment_ctx,
        })

    # ── Balance ───────────────────────────────────────────────────

    def get_balance(self) -> dict:
        """Query the user's spendable Snaplii Cash / cashback balance."""
        return self._get("/v2/balance")

    # ── Bill Pay ──────────────────────────────────────────────────

    def billpay_payee_list(self) -> dict:
        return self._get("/v2/billpay/payees")

    def billpay_payee_detail(self, payee_code: str) -> dict:
        return self._get(f"/v2/billpay/payees/{payee_code}")

    def billpay_history(self, payee_code: str) -> dict:
        return self._get(f"/v2/billpay/payees/{payee_code}/history")

    def billpay_save(self, payee_code: str, first_name: str, last_name: str,
                     amount: str, account: str, phone: str | None = None,
                     email: str | None = None, remark: str | None = None) -> dict:
        body: dict = {
            "payeeCode": payee_code,
            "userFirstName": first_name,
            "userLastName": last_name,
            "payAmount": amount,
            "userAccount": account,
            "picUrlList": [],
        }
        if phone:
            body["userPhone"] = phone
        if email:
            body["userEmail"] = email
        if remark:
            body["remark"] = remark
        return self._post("/v2/billpay/save", json=body)

    def billpay_vouchers(self, pay_code: str, price: str) -> dict:
        return self._post("/v2/billpay/vouchers", json={
            "orderInfo": {
                "orderType": "BILL_PAY",
                "businessChannel": "APP",
                "item": {"itemId": pay_code, "price": price},
                "orderContext": {"giftOrder": "false"},
            }
        })

    def billpay_quote(self, pay_code: str, price: str,
                      voucher_option: str = "BEST_FIT",
                      cashback_option: str = "USE",
                      specified_voucher: str | None = None) -> dict:
        # Pay from Snaplii Cash (SNAPLII_CREDIT) — same as gift cards, agent-autonomous
        payment_ctx: dict = {
            "specifiedPrimaryPaymentMethod": "SNAPLII_CREDIT",
            "voucherOption": voucher_option,
            "cashbackOption": cashback_option,
        }
        if specified_voucher:
            payment_ctx["specifiedVoucher"] = specified_voucher
            payment_ctx["voucherOption"] = "USE"
        return self._post("/v2/quote", json={
            "orderInfo": {
                "orderType": "BILL_PAY",
                "businessChannel": "APP",
                "item": {"itemId": pay_code, "price": price},
                "orderContext": {"giftOrder": "false"},
            },
            "paymentContext": payment_ctx,
        })

    def billpay_create_and_pay(self, pay_code: str, price: str,
                               voucher_option: str = "BEST_FIT",
                               cashback_option: str = "USE",
                               specified_voucher: str | None = None) -> dict:
        # Pay from Snaplii Cash (SNAPLII_CREDIT) — same as gift cards, agent-autonomous
        payment_ctx: dict = {
            "specifiedPrimaryPaymentMethod": "SNAPLII_CREDIT",
            "voucherOption": voucher_option,
            "cashbackOption": cashback_option,
        }
        if specified_voucher:
            payment_ctx["specifiedVoucher"] = specified_voucher
            payment_ctx["voucherOption"] = "USE"
        return self._post("/v2/purchase", json={
            "orderInfo": {
                "orderType": "BILL_PAY",
                "businessChannel": "APP",
                "item": {"itemId": pay_code, "price": price},
                "orderContext": {"giftOrder": "false"},
            },
            "paymentContext": payment_ctx,
            "delivery": {"type": "WALLET", "immediateSend": "false"},
        })

    def billpay_pay_result(self, payment_no: str) -> dict:
        return self._post("/v2/billpay/pay-result", json={"paymentNo": payment_no})

    # API keys are created and managed only in the Snaplii app, never via the CLI.

    # ── P2P Transfers ─────────────────────────────────────────────

    def transfer_create(self, to_phone: str, amount: str, remark: str | None = None,
                        idempotency_key: str | None = None) -> dict:
        """Create a P70 transfer. It stays cancellable until auto_finish_at
        (~5 minutes), then the gateway sends it automatically.

        Generates a fresh UUID Idempotency-Key when none is given. Pass the
        SAME key only when retrying the identical request (after a 202 CREATING
        or an indeterminate timeout) — a fresh key on retry can double the
        transfer. The key used is echoed back in the result, and on errors it
        rides on the raised TransferApiError.
        """
        key = idempotency_key or uuid.uuid4().hex
        body: dict = {"to_phone": to_phone, "amount": amount}
        if remark:
            body["remark"] = remark
        try:
            resp = self._transfer_request("POST", "/v2/transfers", json_body=body,
                                          extra_headers={"Idempotency-Key": key})
        except TransferApiError as e:
            e.idempotency_key = key
            raise
        if isinstance(resp, dict):
            resp.setdefault("idempotency_key", key)
        return resp

    def transfer_cancel(self, order_no: str) -> dict:
        """Cancel a PENDING transfer (allowed until auto_finish_at).

        Returns status CANCELLED, or CANCELLING when the upstream has not
        confirmed yet — poll transfer_get for the final state."""
        return self._transfer_request("POST", f"/v2/transfers/{order_no}/cancel")

    def transfer_finish(self, order_no: str) -> dict:
        """Send the transfer now (moves auto_finish_at to now). The response is
        still PENDING — the background sweeper settles it within ~15s; poll
        transfer_get for the outcome."""
        return self._transfer_request("POST", f"/v2/transfers/{order_no}/finish")

    def transfer_get(self, order_no: str) -> dict:
        """Get one transfer, with fail_code/fail_reason populated when FAILED."""
        return self._transfer_request("GET", f"/v2/transfers/{order_no}")

    def transfer_list(self, status: str | None = None, page: int = 1,
                      page_size: int = 20) -> dict:
        """List the caller's transfers, newest first. `status` is a
        comma-separated filter, e.g. "PENDING,FINISHED"."""
        params = {"page": str(page), "page_size": str(page_size)}
        if status:
            params["status"] = status
        return self._transfer_request("GET", "/v2/transfers", params=params)

    def _transfer_request(self, method: str, path: str, json_body: dict | None = None,
                          params: dict | None = None,
                          extra_headers: dict | None = None) -> dict:
        """Call a /v2/transfers endpoint. These endpoints use their own error
        envelope ({status, code, message, retryable, upstream_code, details})
        rather than the legacy rspMsgCd shape, so errors raise TransferApiError
        with the envelope intact instead of going through _parse_response."""
        token = self._ensure_token()
        url = self._base_url + path
        headers = {"Authorization": f"Bearer {token}"}
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = self._http.request(method, url, json=json_body, params=params,
                                      headers=headers)
        except httpx.ConnectError as e:
            raise GatewayConnectionError(url, e)
        except httpx.TimeoutException:
            # A timed-out create is indeterminate: the transfer may exist. Never
            # auto-create again under a fresh key — surface it as retryable with
            # the same-key instruction (transfer_create attaches the key).
            raise TransferApiError(0, {
                "code": "CLIENT_TIMEOUT",
                "message": ("The request timed out before the gateway answered; "
                            "the operation may or may not have gone through. "
                            "Check 'snaplii transfer list' (or retry the identical "
                            "request with the SAME Idempotency-Key) — never create "
                            "again with a fresh key."),
                "retryable": True,
            }, path)
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        if self._session_rejected(resp.status_code, body):
            error = TransferApiError(resp.status_code, body if isinstance(body, dict) else {}, path)
            self._reject_session(error, token)
            raise error
        if resp.is_success:
            return body if isinstance(body, dict) else {"data": body}
        if not isinstance(body, dict):
            body = {"raw": body}
        raise TransferApiError(resp.status_code, body, path)

    # ── Internal ──────────────────────────────────────────────────

    def _ensure_token(self) -> str:
        token = self._config.get_cached_token(origin=self._origin)
        if token:
            return token
        status = self.auth_status()
        raise AuthError("Authentication is required before this request can be sent.",
                        auth_state=status["auth_state"], reason_code="no_usable_session",
                        next_action=status["next_action"])

    @staticmethod
    def _session_rejected(status_code, body):
        return status_code == 401 or (isinstance(body, dict) and any(
            body.get(key) in ("MCAP9999", "USR_NOT_EXIST")
            for key in ("rspMsgCd", "code", "upstream_code")))

    def _reject_session(self, error, token):
        try:
            cleared = self._config.clear_token(expected_token=token)
            if cleared:
                error.auth_fields = self._auth_fields("reauth_required", "session_rejected")
            else:
                # Another login or logout superseded this request's token.
                # Preserve that state and its runtime-specific recovery action.
                status = self.auth_status()
                error.auth_fields = {"auth_state": status["auth_state"],
                                     "reason_code": "stale_session_rejected",
                                     "next_action": status["next_action"]}
        except ConfigError:
            # Neither clearing nor reading recovery metadata may replace the
            # request error (especially a transfer's idempotency information).
            # These fields require no further access to the broken config.
            error.auth_fields = {
                "auth_state": "session_cache_failed", "reason_code": "session_clear_failed",
                "next_action": {"type": "stop", "reason": "session_cache_failed"},
            }

    def _protected_response(self, response, path, token):
        try:
            body = response.json()
        except ValueError:
            body = {}
        if self._session_rejected(response.status_code, body):
            code = body.get("rspMsgCd", "") if isinstance(body, dict) else ""
            safe = {"friendly_message": "Session rejected. Authenticate before continuing.",
                    "rspMsgCd": code if code in ("MCAP9999", "USR_NOT_EXIST") else ""}
            error = GatewayApiError(response.status_code, safe, path)
            self._reject_session(error, token)
            raise error
        return self._parse_response(response, path)

    def _get(self, path: str, params: dict | None = None) -> dict:
        token = self._ensure_token()
        url = self._base_url + path
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = self._http.get(url, params=params, headers=headers)
        except httpx.ConnectError as e:
            raise GatewayConnectionError(url, e)
        return self._protected_response(resp, path, token)

    def _post(self, path: str, json: dict | None = None, params: dict | None = None) -> dict:
        url = self._base_url + path
        headers = {}
        if path != "/v2/auth/token":
            token = self._ensure_token()
            headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = self._http.post(url, json=json, params=params, headers=headers)
        except httpx.RequestError as e:
            if path == "/v2/auth/token":
                raise self._auth_error("temporary_gateway_error", "auth_transport_failed",
                                       "Could not reach Snaplii to authenticate. Retry authentication later.", "api_key") from None
            # Connect and pool failures happen before anything is sent; any other
            # transport error (read timeout, reset, protocol error) may follow a
            # request the gateway already processed, which matters for a purchase.
            sent = not isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
            raise GatewayConnectionError(url, e, indeterminate=sent)
        if path == "/v2/auth/token":
            return self._parse_login_response(resp, "api_key")
        return self._protected_response(resp, path, token)

    def _delete(self, path: str) -> dict:
        token = self._ensure_token()
        url = self._base_url + path
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = self._http.delete(url, headers=headers)
        except httpx.ConnectError as e:
            raise GatewayConnectionError(url, e)
        return self._protected_response(resp, path, token)

    # Human-readable error messages for common error codes
    _ERROR_MESSAGES = {
        "MACP6005": "Payment service error. This may be a temporary issue — please wait a moment and retry. If it persists, check your Snaplii Cash balance in the app.",
        "MACP6006": "Service call failed. The downstream gift card service is temporarily unavailable. Please try again later.",
        "MCAP9999": "Session expired. Please run 'snaplii init' to re-authenticate.",
        "MCA20004": "That payment method isn't enabled on this account. Purchases use the default Snaplii Cash (SNAPLII_CREDIT), which works — retry without specifying a payment method.",
        "MCA20101": "Invalid API key format or request parameters.",
        "MCA20102": "This API key has been deactivated.",
        "MCA20103": "An API key with this name already exists. Please choose a different name.",
        "MCA20104": "API key limit reached. Delete an existing key before creating a new one.",
        "MCA20105": "API key not found.",
        "MCA20106": "This API key does not belong to your account.",
        "APP_VERSION_NOT_SUPPORT": "App version too low. Minimum version 4.8.0 required.",
        "USR_NOT_EXIST": "User not found in session. Please re-authenticate.",
        "ORDER_STATUS_INCORRECT": "Order status error. The order may not exist or is not in a payable state.",
        "ORDER_CREATION_FAILED": "Order creation failed. You may have reached a spending limit.",
        "AUTH_VERIFY_FAILED": "Authentication verification failed.",
    }

    @classmethod
    def _parse_response(cls, resp: httpx.Response, path: str):
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        if resp.is_success:
            if isinstance(body, dict):
                rsp_code = body.get("rspMsgCd", "")
                if not isinstance(rsp_code, str):
                    raise GatewayApiError(resp.status_code, {}, path)
                if rsp_code and not rsp_code.endswith("00000"):
                    cls._attach_friendly_message(body, rsp_code)
                    raise GatewayApiError(resp.status_code, body, path)
            return body
        # Non-success HTTP. If the body carries a business error code (e.g. a 422
        # business rejection like a spending-limit hit), surface its real message
        # instead of a generic status-based fallback.
        if not isinstance(body, dict):
            body = {"raw": body}
        rsp_code = body.get("rspMsgCd", "")
        if not isinstance(rsp_code, str):
            raise GatewayApiError(resp.status_code, {}, path)
        if rsp_code:
            cls._attach_friendly_message(body, rsp_code)
        raise GatewayApiError(resp.status_code, body, path)

    @classmethod
    def _attach_friendly_message(cls, body: dict, rsp_code: str) -> None:
        """Set body['friendly_message'] from the error-code map, or fall back to the
        upstream message text (rspMsgInf / rspMsgInfo)."""
        friendly = cls._ERROR_MESSAGES.get(rsp_code)
        if not friendly:
            friendly = body.get("rspMsgInf") or body.get("rspMsgInfo")
        if friendly:
            body["friendly_message"] = friendly
