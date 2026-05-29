from __future__ import annotations

import httpx

from snaplii.config_store import ConfigStore
from snaplii.exceptions import ConfigError, GatewayApiError, GatewayConnectionError


class GatewayClient:
    def __init__(self, base_url: str, config_store: ConfigStore):
        self._base_url = base_url.rstrip("/")
        if not self._base_url.startswith("https://") and "localhost" not in self._base_url and "127.0.0.1" not in self._base_url:
            raise ConfigError("Gateway URL must use HTTPS for non-local connections.")
        self._config = config_store
        self._http = httpx.Client(timeout=30.0)

    # ── Auth ──────────────────────────────────────────────────────

    def login(self, agent_id: str, api_key: str) -> dict:
        resp = self._post("/v2/auth/token", json={
            "agent_id": agent_id,
            "api_key": api_key,
        })
        token = resp.get("access_token")
        expires_in = resp.get("expires_in", 3600)
        if token:
            self._config.cache_token(token, expires_in)
        return resp

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

    def get_all_card_tags(self, channel: str = "HOME_PAGE", location_prov: str = "CA") -> dict:
        resp = self._get("/v2/card-brands", params={
            "channel": channel,
            "locationProv": location_prov,
        })
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

    # ── Purchase ──────────────────────────────────────────────────

    def create_order_and_pay(
        self,
        item_id: str,
        price: str,
        payment_method: str = "SNAPLII_CREDIT",
        payment_token: str | None = None,
        location_prov: str = "CA",
    ) -> dict:
        payment_ctx = {
            "specifiedPrimaryPaymentMethod": payment_method,
            "voucherOption": "BEST_FIT",
            "cashbackOption": "USE",
        }
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
            "locationProv": location_prov,
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
                               location_prov: str = "ON",
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
            "locationProv": location_prov,
        })

    def billpay_pay_result(self, payment_no: str) -> dict:
        return self._post("/v2/billpay/pay-result", json={"paymentNo": payment_no})

    # ── API key management ────────────────────────────────────────

    def create_api_key(self, name: str, scope: str, consumption_limit: float | None = None) -> dict:
        params = {"name": name, "scope": scope}
        if consumption_limit is not None:
            params["consumptionLimit"] = str(consumption_limit)
        return self._post("/v2/apikeys", params=params)

    def list_api_keys(self) -> dict:
        return self._get("/v2/apikeys")

    def delete_api_key(self, key_id: str) -> dict:
        return self._delete(f"/v2/apikeys/{key_id}")

    # ── Internal ──────────────────────────────────────────────────

    def _ensure_token(self) -> str:
        token = self._config.get_cached_token()
        if token:
            return token
        raise ConfigError(
            "Token expired or missing. Run 'snaplii init' to re-authenticate with your API key."
        )

    def _get(self, path: str, params: dict | None = None) -> dict:
        token = self._ensure_token()
        url = self._base_url + path
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = self._http.get(url, params=params, headers=headers)
        except httpx.ConnectError as e:
            raise GatewayConnectionError(url, e)
        return self._parse_response(resp, path)

    def _post(self, path: str, json: dict | None = None, params: dict | None = None) -> dict:
        url = self._base_url + path
        headers = {}
        if path != "/v2/auth/token":
            token = self._ensure_token()
            headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = self._http.post(url, json=json, params=params, headers=headers)
        except httpx.ConnectError as e:
            raise GatewayConnectionError(url, e)
        return self._parse_response(resp, path)

    def _delete(self, path: str) -> dict:
        token = self._ensure_token()
        url = self._base_url + path
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = self._http.delete(url, headers=headers)
        except httpx.ConnectError as e:
            raise GatewayConnectionError(url, e)
        return self._parse_response(resp, path)

    # Human-readable error messages for common error codes
    _ERROR_MESSAGES = {
        "MACP6005": "Payment service error. This may be a temporary issue — please wait a moment and retry. If it persists, check your Snaplii Cash balance in the app.",
        "MACP6006": "Service call failed. The downstream gift card service is temporarily unavailable. Please try again later.",
        "MCAP9999": "Session expired. Please run 'snaplii init' to re-authenticate.",
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
                if rsp_code and not rsp_code.endswith("00000"):
                    friendly = cls._ERROR_MESSAGES.get(rsp_code)
                    if friendly:
                        body["friendly_message"] = friendly
                    raise GatewayApiError(resp.status_code, body, path)
            return body
        if not isinstance(body, dict):
            body = {"raw": body}
        raise GatewayApiError(resp.status_code, body, path)
