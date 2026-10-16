from __future__ import annotations

import re
import uuid
from urllib.parse import urlsplit

import httpx

from snaplii.config_store import ConfigStore
from snaplii import auth
from snaplii.exceptions import (
    ItemCheckUnavailableError,
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


def brand_detail(brand_resp) -> dict:
    """The brand object of a brand-detail reply, given directly or wrapped in "data"."""
    if not isinstance(brand_resp, dict):
        return {}
    data = brand_resp.get("data")
    return data if isinstance(data, dict) else brand_resp


def card_cashback_percent(card: dict):
    """A card's cashback percent as the catalog states it: discount, else regularDiscount."""
    return card.get("discount") or card.get("regularDiscount")


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
        disc = card_cashback_percent(c)
        if disc:
            entry["cashback_percent"] = disc
        out.append(entry)
    return out


def _unreadable_transfer(status_code: int, path: str) -> TransferApiError:
    return TransferApiError(status_code, {
        "code": "CLIENT_UNREADABLE_RESPONSE",
        "message": ("The gateway sent an unreadable response; the operation may "
                    "or may not have gone through. Check 'snaplii transfer list' "
                    "(or retry the identical request with the SAME Idempotency-Key) "
                    "— never create again with a fresh key."),
        "retryable": True,
    }, path)


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

    def login(self, agent_id: str, api_key: str, *, remember_base_url: bool = False) -> dict:
        auth.require_login_origin(self._origin)
        if not auth.valid_api_key(api_key):
            # Never send a vault reference, surrogate or hash as a key, and never
            # echo what was given: the message names the format, not the value.
            if self.auth_status()["host"] == "muse":
                raise self._auth_error("auth_required", "api_key_format_invalid",
                                       "That is not a Snaplii API key. " + self._MUSE_USE_STORED_KEY, "vault")
            raise self._auth_error("invalid_key", "api_key_format_invalid",
                                   "That is not a Snaplii API key. A key is snp_sk_live_ followed by "
                                   "32 letters and digits; copy it again from the Snaplii app.", "api_key")
        resp = self._post("/v2/auth/token", json={
            "agent_id": agent_id,
            "api_key": api_key,
        })
        return self._finish_login(resp, agent_id=agent_id, auth_method="api_key",
                                  remember_base_url=remember_base_url)

    def login_via_vault(self, agent_id: str, *, remember_base_url: bool = False) -> dict:
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
        return self._finish_login(body, agent_id=agent_id, auth_method="vault",
                                  remember_base_url=remember_base_url)

    # The gateway's reply when it refuses a key; its message may carry an error
    # code, e.g. "... (MCA20101: ...)".
    _GATEWAY_KEY_REJECTION = "Snaplii core rejected the credentials"
    # In Muse the user's key is in the secure credential store, so a raw key that
    # fails was typed or rebuilt by the agent: send it back to the stored one.
    _MUSE_USE_STORED_KEY = ("In Muse the real key is already in the secure credential store; "
                            "do not type, rebuild or copy a key yourself. "
                            "Run `snaplii init --vault-auth` to use the stored key.")

    def _parse_login_response(self, response, method):
        try:
            return self._parse_response(response, "/v2/auth/token")
        except GatewayApiError as exc:
            if exc.body.get("unreadable"):
                return {}  # _finish_login reports the missing access token
            message = exc.body.get("message")
            gateway_rejected = (exc.status_code in (401, 403) and isinstance(message, str)
                                and message.startswith(self._GATEWAY_KEY_REJECTION))
            code = exc.body.get("rspMsgCd")
            if not code and gateway_rejected:
                found = re.search(r"\((MCA\d+)", message)
                code = found.group(1) if found else ""
            code = code if isinstance(code, str) and code in self._ERROR_MESSAGES else ""
            safe = {"rspMsgCd": code}
            if code:
                safe["friendly_message"] = self._ERROR_MESSAGES[code]
            if gateway_rejected or code.startswith("MCA201"):
                state, reason = "invalid_key", "auth_gateway_rejected"
            elif exc.status_code in (401, 403):
                # Something other than the gateway refused the request (a proxy, a
                # host's credential layer, a wrong address): the key was never judged.
                state, reason = "auth_response_invalid", "auth_rejected_unverified"
                safe["friendly_message"] = (
                    "Authentication was rejected before Snaplii checked the key, so the key may still be "
                    "valid. Check the gateway address and how the key reaches it before replacing the key.")
            else:
                state = "temporary_gateway_error" if exc.status_code >= 500 else "auth_response_invalid"
                reason = "auth_gateway_rejected"
            if state == "invalid_key" and method == "api_key" and self.auth_status()["host"] == "muse":
                state, method = "auth_required", "vault"
                safe["friendly_message"] = "That key was not accepted. " + self._MUSE_USE_STORED_KEY
            error = GatewayApiError(exc.status_code, safe, "/v2/auth/token")
            error.auth_fields = self._auth_fields(state, reason, method)
            raise error from None

    def _finish_login(self, resp: dict, *, agent_id, auth_method: str,
                      remember_base_url: bool = False) -> dict:
        """Shared tail of every login path: validate the token and cache it. With
        remember_base_url, this gateway becomes the saved default in the same write."""
        body = resp if isinstance(resp, dict) else {}
        token = body.get("access_token")
        if not token:
            error = GatewayApiError(200, {"friendly_message": "Login did not return an access token."}, "/v2/auth/token")
            error.auth_fields = self._auth_fields("auth_response_invalid", "missing_access_token", auth_method)
            raise error
        expires_in = body.get("expires_in", 3600)
        self._config.commit_session(token, expires_in, agent_id=agent_id,
                                    auth_method=auth_method, token_origin=self._origin,
                                    country=body.get("country"),
                                    base_url=self._base_url if remember_base_url else None)
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
        except httpx.RequestError as e:
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

    def list_all_user_cards(self, status: str = "ACTIVE", page_size: int = 100) -> list:
        """Every owned card. The list carries no total, so a short page ends it;
        a page identical to the one before means the server ignored paging."""
        cards, previous, page = [], None, 1
        while True:
            resp = self.list_user_cards(status=status, page=page, page_size=page_size)
            rows = resp.get("data") if isinstance(resp, dict) else None
            rows = rows if isinstance(rows, list) else []
            if rows == previous:
                break
            cards.extend(rows)
            if len(rows) < page_size:
                break
            previous, page = rows, page + 1
        return cards

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

    def validate_amount(self, item_id: str, price) -> dict:
        """Guard quote/purchase: `item_id` must be exactly {cardBrandId}-{cardTemplateId}
        with a template that is a card of that brand, and `price` must fall within
        that card's allowed denomination.

        Returns {"item_id", "brand_name"} for the verified card. Raises ItemIdError for a
        malformed item_id, a brand the catalog does not have, or a template the brand does
        not list; ItemCheckUnavailableError when the catalog cannot be read; and
        AmountValidationError when the amount is out of range. Nothing is sent unless the
        card is verified, so an ID that could name a different card never reaches the
        gateway. This mirrors the app's UI check (DrawerBottomInputAmount) which the agent
        path would otherwise bypass.
        """
        if not isinstance(item_id, str) or not _ITEM_ID.match(item_id):
            raise ItemIdError(
                "item_id must be exactly {cardBrandId}-{cardTemplateId}, copied verbatim from "
                "browse brand (e.g. CB00000000000086-CT000000003618); got %r." % (item_id,),
                item_id=item_id if isinstance(item_id, str) else "")
        brand_id, _, template_id = item_id.partition("-")

        try:
            detail = self.get_card_brand_by_id(brand_id)
        except ConfigError:
            raise  # authentication or configuration state: report it as it is
        except GatewayApiError as e:
            if e.auth_fields or e.status_code in (401, 403):
                raise  # a session or permission problem, not an item problem
            if e.status_code >= 500 and self._brand_listed(brand_id) is False:
                # After a failed detail lookup, readable brand lists that do not name
                # the brand mean the item_id is wrong.
                raise ItemIdError(
                    "Brand %s is not in the brand lists you can browse (browse tags), so item_id "
                    "%s was not copied from browse brand." % (brand_id, item_id),
                    item_id=item_id) from e
            if e.status_code >= 500 or e.status_code == 429 or (
                    isinstance(e.body, dict) and e.body.get("unreadable")):
                raise ItemCheckUnavailableError(
                    "The catalog could not be read, so item_id %s could not be verified."
                    % item_id, item_id=item_id) from e
            raise ItemIdError(
                "Brand %s was not found in the catalog, so item_id %s cannot be the card the "
                "user chose." % (brand_id, item_id), item_id=item_id) from e
        except SnapliiCliError as e:
            raise ItemCheckUnavailableError(
                "The catalog could not be reached, so item_id %s could not be verified."
                % item_id, item_id=item_id) from e

        # A reply we cannot read says nothing about the ID; an empty brand says it is wrong.
        raw_cards = brand_detail(detail).get("cards")
        data = detail.get("data") if isinstance(detail, dict) else None
        if (not isinstance(detail, dict) or (data is not None and not isinstance(data, dict))
                or (raw_cards is not None and not isinstance(raw_cards, list))):
            raise ItemCheckUnavailableError(
                "The catalog sent an unreadable reply, so item_id %s could not be verified."
                % item_id, item_id=item_id)
        brand = brand_detail(detail)
        cards = [c for c in raw_cards or [] if isinstance(c, dict)]
        card = next((c for c in cards if c.get("cardTemplateId") == template_id), None)
        if not card:
            raise ItemIdError(
                "Brand %s has no card %s, so this item_id would not buy the card the user "
                "chose." % (brand_id, template_id), item_id=item_id)
        checked = {"item_id": item_id}
        desc = brand.get("desc")
        brand_name = ((desc.get("name") if isinstance(desc, dict) else None)
                      or brand.get("name") or brand.get("alternativeName"))
        if isinstance(brand_name, str) and brand_name.strip():
            checked["brand_name"] = brand_name.strip()

        try:
            amount = float(price)
        except (TypeError, ValueError):
            return checked  # malformed price — let the server reject it

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
        return checked

    def _brand_listed(self, brand_id: str):
        """Whether the account's brand lists (both channels) name brand_id: True as soon as
        one does, False when every list is read in full and none does, None when a list
        cannot be read or is malformed, or all are empty."""
        listed = set()
        for channel in ("HOME_PAGE", "SEND_GIFT"):
            try:
                tags = self.get_all_card_tags(channel=channel)
            except ConfigError:
                raise
            except GatewayApiError as e:
                if e.auth_fields or e.status_code in (401, 403):
                    raise
                return None
            except SnapliiCliError:
                return None
            rows = tags.get("data") if isinstance(tags, dict) else None
            if not isinstance(rows, list):
                return None
            for tag in rows:
                if not isinstance(tag, dict):
                    return None
                brands = tag.get("cardBrands")
                if brands is None:
                    continue  # an empty category leaves cardBrands out (or sends null)
                if not isinstance(brands, list):
                    return None
                for brand in brands:
                    bid = brand.get("cardBrandId") if isinstance(brand, dict) else None
                    if not isinstance(bid, str) or not bid:
                        return None
                    listed.add(bid)
            if brand_id in listed:
                return True
        return False if listed else None

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
            payment_ctx["voucherOption"] = "USE"   # match create_order_and_pay
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
            if not (isinstance(resp, dict) and (resp.get("order_no") or resp.get("status"))):
                raise _unreadable_transfer(200, "/v2/transfers")
        except TransferApiError as e:
            e.idempotency_key = key
            raise
        resp.setdefault("idempotency_key", key)
        return resp

    def transfer_cancel(self, order_no: str) -> dict:
        """Cancel a PENDING transfer (allowed until auto_finish_at).

        Returns status CANCELLED, or CANCELLING when the upstream has not
        confirmed yet — poll transfer_get for the final state."""
        return self._transfer_request("POST", f"/v2/transfers/{order_no}/cancel")

    def transfer_finish(self, order_no: str) -> dict:
        """Send the transfer now (moves auto_finish_at to now). The response is
        still PENDING and normally settles within ~15s; poll
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
        except httpx.RequestError as e:
            # A timeout, a reset connection or a broken response may follow a request
            # the gateway already processed, so the transfer may exist. Never
            # auto-create again under a fresh key — surface it as retryable with
            # the same-key instruction (transfer_create attaches the key).
            timed_out = isinstance(e, httpx.TimeoutException)
            raise TransferApiError(0, {
                "code": "CLIENT_TIMEOUT" if timed_out else "CLIENT_TRANSPORT_ERROR",
                "message": (("The request timed out" if timed_out else "The connection failed")
                            + " before the gateway answered; "
                            "the operation may or may not have gone through. "
                            "Check 'snaplii transfer list' (or retry the identical "
                            "request with the SAME Idempotency-Key) — never create "
                            "again with a fresh key."),
                "retryable": True,
            }, path)
        try:
            body = resp.json()
        except Exception:
            if resp.is_success:
                # The gateway answered but the reply cannot be read: as with a
                # timeout, the transfer may exist, so keep the same-key rule.
                raise _unreadable_transfer(resp.status_code, path)
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
        except httpx.RequestError as e:
            raise GatewayConnectionError(url, e)  # a read is safe to retry
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
        "MCAP2107": "The gateway rejected this item_id, so nothing was charged.",
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
            if resp.is_success or path == "/v2/purchase":
                # A reply we cannot read is not a result. After a purchase it leaves
                # the outcome unknown whatever its status: a business rejection is
                # readable, and a rejected session never reaches this point.
                raise GatewayApiError(resp.status_code, {"unreadable": True}, path)
            body = {"raw": resp.text}
        if resp.is_success:
            payment = path == "/v2/purchase"
            if isinstance(body, dict):
                rsp_code = body.get("rspMsgCd", "")
                if not isinstance(rsp_code, str):
                    raise GatewayApiError(resp.status_code, {"unreadable": True} if payment else {}, path)
                if rsp_code and not rsp_code.endswith("00000"):
                    cls._attach_friendly_message(body, rsp_code)
                    raise GatewayApiError(resp.status_code, body, path)
            if payment and not (isinstance(body, dict) and body):
                # null, a list or an empty object says nothing about the payment.
                raise GatewayApiError(resp.status_code, {"unreadable": True}, path)
            return body
        # Non-success HTTP. If the body carries a business error code (e.g. a 422
        # business rejection like a spending-limit hit), surface its real message
        # instead of a generic status-based fallback.
        rsp_code = body.get("rspMsgCd", "") if isinstance(body, dict) else ""
        if path == "/v2/purchase" and not cls._readable_rejection(body):
            # Only a readable rejection says the payment did not happen.
            raise GatewayApiError(resp.status_code, {"unreadable": True}, path)
        if not isinstance(body, dict):
            body = {"raw": body}
        if not isinstance(rsp_code, str):
            raise GatewayApiError(resp.status_code, {}, path)
        if rsp_code:
            cls._attach_friendly_message(body, rsp_code)
        raise GatewayApiError(resp.status_code, body, path)

    @staticmethod
    def _readable_rejection(body) -> bool:
        """True when a reply says why it was refused: a code or a text message."""
        if not isinstance(body, dict):
            return False
        code = body.get("rspMsgCd", "")
        if not isinstance(code, str):
            return False
        return bool(code.strip()) or any(
            isinstance(body.get(key), str) and body[key].strip()
            for key in ("rspMsgInf", "rspMsgInfo", "message"))

    @classmethod
    def _attach_friendly_message(cls, body: dict, rsp_code: str) -> None:
        """Set body['friendly_message'] from the error-code map, or fall back to the
        upstream message text (rspMsgInf / rspMsgInfo)."""
        friendly = cls._ERROR_MESSAGES.get(rsp_code)
        if not friendly:
            friendly = body.get("rspMsgInf") or body.get("rspMsgInfo")
        if friendly:
            body["friendly_message"] = friendly
