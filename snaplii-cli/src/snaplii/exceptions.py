class SnapliiCliError(Exception):
    pass


class GatewayApiError(SnapliiCliError):
    def __init__(self, status_code: int, body: dict, endpoint: str):
        self.status_code = status_code
        self.body = body
        self.endpoint = endpoint
        super().__init__(f"API error {status_code} on {endpoint}")

    def to_dict(self) -> dict:
        friendly = self.body.get("friendly_message")
        error_code = self.body.get("rspMsgCd", "")
        if not friendly:
            if self.status_code == 502:
                friendly = "Gateway temporarily unavailable. Please wait a moment and try again."
            elif self.status_code == 401 or self.status_code == 403:
                friendly = "Authentication failed. Run 'snaplii init' to re-authenticate."
            elif self.status_code == 404:
                friendly = "Endpoint not found. Check your gateway URL with 'snaplii config show'."
            elif error_code:
                friendly = f"Request failed with code {error_code}. Check the gateway logs for details."
            else:
                raw = self.body.get("rspMsgInf") or self.body.get("message") or self.body.get("raw", "")
                friendly = f"Request failed (HTTP {self.status_code}). {raw}".strip()
        return {
            "error": friendly,
            "error_code": error_code,
            "endpoint": self.endpoint,
        }


class GatewayConnectionError(SnapliiCliError):
    def __init__(self, url: str, cause: Exception):
        self.url = url
        self.cause = cause
        super().__init__(f"Connection failed: {url}")

    def to_dict(self) -> dict:
        return {
            "error": "Connection failed",
            "url": self.url,
            "cause": str(self.cause),
        }


class AmountValidationError(SnapliiCliError):
    """Requested amount is outside the brand's allowed denomination range.

    Raised client-side before quote/purchase so an out-of-range order never
    reaches the backend (which currently accepts it, returns you_pay=0, then
    fails the card and refunds — burning a round-trip and a Snaplii Cash debit).
    """

    def __init__(self, message: str, *, item_id: str = "", amount=None,
                 min_amount=None, max_amount=None, fixed=None):
        self.message = message
        self.item_id = item_id
        self.amount = amount
        self.min_amount = min_amount
        self.max_amount = max_amount
        self.fixed = fixed
        super().__init__(message)

    def to_dict(self) -> dict:
        out = {"error": "amount_out_of_range", "message": self.message}
        if self.item_id:
            out["item_id"] = self.item_id
        if self.amount is not None:
            out["requested_amount"] = self.amount
        if self.fixed is not None:
            out["fixed_amount"] = self.fixed
        else:
            if self.min_amount is not None:
                out["min_amount"] = self.min_amount
            if self.max_amount is not None:
                out["max_amount"] = self.max_amount
        return out


class ConfigError(SnapliiCliError):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"error": "Configuration error", "message": self.message}


class TransferApiError(SnapliiCliError):
    """Error from a /v2/transfers endpoint.

    Those endpoints return their own envelope ({status, code, message,
    retryable, upstream_code, details}) instead of the legacy rspMsgCd shape,
    and the gateway's message is already the meaningful, human-readable one —
    so the envelope is surfaced as-is.
    """

    def __init__(self, status_code: int, body: dict, endpoint: str):
        self.status_code = status_code
        self.body = body or {}
        self.endpoint = endpoint
        # Set by GatewayClient.transfer_create so a retry can reuse the key.
        self.idempotency_key = None
        super().__init__(f"Transfer API error {status_code} on {endpoint}")

    def to_dict(self) -> dict:
        message = (self.body.get("message") or self.body.get("raw")
                   or f"Transfer request failed (HTTP {self.status_code}).")
        out = {
            "error": message,
            "code": self.body.get("code", ""),
            "retryable": bool(self.body.get("retryable", False)),
            "endpoint": self.endpoint,
        }
        if self.body.get("upstream_code"):
            out["upstream_code"] = self.body["upstream_code"]
        if self.body.get("details"):
            out["details"] = self.body["details"]
        if self.idempotency_key:
            out["idempotency_key"] = self.idempotency_key
            if out["retryable"]:
                out["retry_hint"] = (
                    "If you retry, resend the IDENTICAL request with "
                    f"--idempotency-key {self.idempotency_key} — never a fresh key."
                )
        return out
