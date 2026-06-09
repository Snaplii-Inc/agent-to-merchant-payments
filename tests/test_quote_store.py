import pytest

from snaplii.security.quote_store import QuoteStore


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_issue_and_validate_roundtrip():
    store = QuoteStore(ttl_seconds=300, clock=Clock())
    token = store.issue("ITEM-1", "50", {"you_pay": "46"})
    rec = store.validate(token, "ITEM-1", "50")
    assert rec.canonical == {"you_pay": "46"}


def test_expired_token_is_rejected():
    clock = Clock()
    store = QuoteStore(ttl_seconds=300, clock=clock)
    token = store.issue("ITEM-1", "50", {})
    clock.t += 301
    with pytest.raises(ValueError, match="expired"):
        store.validate(token, "ITEM-1", "50")


def test_single_use_after_consume():
    store = QuoteStore(ttl_seconds=300, clock=Clock())
    token = store.issue("ITEM-1", "50", {})
    store.validate(token, "ITEM-1", "50")  # still valid before consume
    store.consume(token)
    with pytest.raises(ValueError, match="used"):
        store.validate(token, "ITEM-1", "50")


def test_item_or_price_mismatch_rejected():
    store = QuoteStore(ttl_seconds=300, clock=Clock())
    token = store.issue("ITEM-1", "50", {})
    with pytest.raises(ValueError, match="match"):
        store.validate(token, "ITEM-2", "50")
    with pytest.raises(ValueError, match="match"):
        store.validate(token, "ITEM-1", "75")


def test_unknown_token_rejected():
    store = QuoteStore(ttl_seconds=300, clock=Clock())
    with pytest.raises(ValueError, match="missing"):
        store.validate("nope", "ITEM-1", "50")


def test_context_stored_and_returned_on_validate():
    store = QuoteStore(ttl_seconds=300, clock=Clock())
    ctx = {"voucher_option": "NOT_USE", "cashback_option": "NOT_USE", "specified_voucher": "V-9"}
    token = store.issue("ITEM-1", "50", {"you_pay": "46"}, context=ctx)
    rec = store.validate(token, "ITEM-1", "50")
    assert rec.context == ctx


def test_context_defaults_to_none():
    store = QuoteStore(ttl_seconds=300, clock=Clock())
    token = store.issue("ITEM-1", "50", {"you_pay": "46"})
    rec = store.validate(token, "ITEM-1", "50")
    assert rec.context is None
