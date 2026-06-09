"""In-memory, single-use, short-TTL store mapping a confirmation token to the
canonical quote a user must approve. The token is the seam for a future
gateway-issued token: the contract (issue on quote, validate on purchase) does
not change when enforcement moves server-side."""

from __future__ import annotations

import secrets
import time as _time
from dataclasses import dataclass

DEFAULT_TTL_SECONDS = 300


@dataclass
class QuoteRecord:
    item_id: str
    price: str
    canonical: dict
    expires_at: float
    used: bool = False
    context: dict | None = None


class QuoteStore:
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS, clock=_time.time):
        self._ttl = ttl_seconds
        self._clock = clock
        self._records: dict[str, QuoteRecord] = {}

    def issue(self, item_id: str, price: str, canonical: dict, context: dict | None = None) -> str:
        token = secrets.token_urlsafe(24)
        self._records[token] = QuoteRecord(
            item_id=str(item_id),
            price=str(price),
            canonical=canonical,
            expires_at=self._clock() + self._ttl,
            context=context,
        )
        return token

    def _live(self, token: str) -> QuoteRecord | None:
        rec = self._records.get(token)
        if rec is None or rec.used or self._clock() >= rec.expires_at:
            return None
        return rec

    def validate(self, token: str, item_id: str, price: str) -> QuoteRecord:
        """Return the live record matching item_id+price, or raise ValueError
        with a reason: missing/expired/used/mismatch."""
        rec = self._records.get(token)
        if rec is None:
            raise ValueError("confirmation_token is missing or unknown")
        if rec.used:
            raise ValueError("confirmation_token has already been used")
        if self._clock() >= rec.expires_at:
            raise ValueError("confirmation_token has expired")
        if rec.item_id != str(item_id) or rec.price != str(price):
            raise ValueError("confirmation_token does not match this item/price")
        return rec

    def consume(self, token: str) -> None:
        rec = self._records.get(token)
        if rec is not None:
            rec.used = True
