class SnapliiCliError(Exception):
    pass


class GatewayApiError(SnapliiCliError):
    def __init__(self, status_code: int, body: dict, endpoint: str):
        self.status_code = status_code
        self.body = body
        self.endpoint = endpoint
        self.auth_fields = {}
        super().__init__(f"API error {status_code} on {endpoint}")

    def to_dict(self) -> dict:
        friendly = self.body.get("friendly_message")
        if self.auth_fields.get("reason_code") == "stale_session_rejected":
            friendly = "The session used by this request was rejected. Check current authentication state before continuing."
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
                friendly = f"Request failed (HTTP {self.status_code})."
                reason = (self.body.get("rspMsgInf") or self.body.get("rspMsgInfo")
                          or self.body.get("message") or self.body.get("raw"))
                # Login responses are sanitized before they get here; other
                # endpoints carry the business reason the agent needs.
                if self.endpoint != "/v2/auth/token" and isinstance(reason, str) and reason.strip():
                    friendly += " " + reason.strip()[:500]
        return {
            "error": friendly,
            "error_code": error_code,
            "endpoint": self.endpoint,
            **self.auth_fields,
        }


class GatewayConnectionError(SnapliiCliError):
    def __init__(self, url: str, cause: Exception, *, indeterminate: bool = False):
        self.url = url
        self.cause = cause
        # True when the request may already have been sent and processed (read
        # timeout, reset, protocol error), so a blind retry could double a charge.
        self.indeterminate = indeterminate
        super().__init__(f"Connection failed: {url}")

    def to_dict(self) -> dict:
        if self.indeterminate:
            return {
                "error": ("The request was sent but no response arrived; it may or may "
                          "not have been processed."),
                "url": self.url,
                "cause": "transport_error",
                "outcome": "indeterminate",
                "retry_hint": ("Do not retry blindly: check the outcome first (owned gift "
                               "cards, bill pay result, or transfer list) before sending "
                               "the request again."),
            }
        return {
            "error": "Connection failed",
            "url": self.url,
            "cause": "transport_error",
            "outcome": "not_sent",
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


class ItemIdError(SnapliiCliError):
    """The gift-card item_id is not exactly {cardBrandId}-{cardTemplateId}, or its template
    is not a card of that brand. Raised before quote/purchase so the order never reaches
    the gateway with an ID that could name a different card."""

    def __init__(self, message: str, *, item_id: str = ""):
        self.message = message
        self.item_id = item_id
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"error": "invalid_item_id", "message": self.message, "item_id": self.item_id}


class ConfigError(SnapliiCliError):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"error": "Configuration error", "message": self.message}


class AuthError(ConfigError):
    """Fixed, secret-free authentication state; never copy upstream text here."""

    def __init__(self, message: str, *, auth_state: str, reason_code: str, next_action: dict):
        self.auth_state = auth_state
        self.reason_code = reason_code
        self.next_action = next_action
        super().__init__(message)

    def to_dict(self) -> dict:
        return {**super().to_dict(), "auth_state": self.auth_state,
                "reason_code": self.reason_code, "next_action": self.next_action}


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
        self.auth_fields = {}
        super().__init__(f"Transfer API error {status_code} on {endpoint}")

    def to_dict(self) -> dict:
        if self.auth_fields:
            code = self.body.get("code", "")
            message = ("The session used by this request was rejected. Check current authentication state before continuing."
                       if self.auth_fields.get("reason_code") == "stale_session_rejected"
                       else "Session rejected. Authenticate before continuing.")
            out = {"error": message,
                   "code": code if code in ("MCAP9999", "USR_NOT_EXIST", "UNAUTHORIZED", "AUTH_REQUIRED") else "",
                   "retryable": False, "endpoint": self.endpoint, **self.auth_fields}
            if self.idempotency_key:
                out["idempotency_key"] = self.idempotency_key
                out["retry_hint"] = "Check the transfer status before retrying. If a retry is appropriate, reuse the SAME idempotency key and identical request; never replay automatically."
            return out
        message = self.body.get("message")
        if not message and isinstance(self.body.get("errors"), list):
            # Field-validation 400s use the common shape: message is null and
            # the per-field messages live in `errors` — join them so the agent
            # sees "amount: must be …" instead of a generic HTTP failure.
            parts = [f"{e.get('field', '?')}: {e.get('message', '')}"
                     for e in self.body["errors"] if isinstance(e, dict)]
            message = "; ".join(p for p in parts if p) or None
        if not message:
            message = (self.body.get("raw")
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
            code = out["code"]
            if code == "QUOTE_EXPIRED":
                # Spec: the quote is gone — create again with a NEW key.
                out["retry_hint"] = "The quote expired before an order was created. Create again with a fresh key (just re-run the command without --idempotency-key)."
            elif out["retryable"] and (self.status_code in (0, 502, 503, 504)
                                       or code in ("TRANSFER_INDETERMINATE",
                                                   "CLIENT_TIMEOUT",
                                                   "CONCURRENT_DUPLICATE",
                                                   "UPSTREAM_ERROR")):
                # Indeterminate: the transfer may exist — only the SAME key is safe.
                out["retry_hint"] = (
                    "If you retry, resend the IDENTICAL request with "
                    f"--idempotency-key {self.idempotency_key} — never a fresh key."
                )
        return out
