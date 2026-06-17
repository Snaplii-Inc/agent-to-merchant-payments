import asyncio
import json

import server

from snaplii.security.quote_store import QuoteStore


# ── Test helpers ────────────────────────────────────────────────────────────


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs


class FakeClient:
    def __init__(self):
        self.charges = []
        self.billpay_charges = []
        self.last_kwargs = None

    def create_order_and_pay(self, **kwargs):
        self.charges.append(kwargs)
        self.last_kwargs = kwargs
        return {"orderNo": "ORD-1", "status": "SUCCESS"}

    def billpay_create_and_pay(self, **kwargs):
        self.billpay_charges.append(kwargs)
        self.last_kwargs = kwargs
        return {"orderNo": "B-1", "paymentNo": "P-1", "orderStatus": "SUCCESS"}


ITEM = "CB86-TPL1"
PRICE = "50.00"
PAY_CODE = "PC-123"


def _wire(monkeypatch, clock=None):
    """Install a fresh QuoteStore and FakeClient on the server module. Returns
    (store, client, clock)."""
    clock = clock or FakeClock()
    store = QuoteStore(ttl_seconds=300, clock=clock)
    client = FakeClient()
    monkeypatch.setattr(server, "_QUOTE_STORE", store)
    monkeypatch.setattr(server, "_get_client", lambda: client)
    return store, client, clock


def _purchase(token=None):
    args = {"item_id": ITEM, "price": PRICE}
    if token is not None:
        args["confirmation_token"] = token
    res = asyncio.run(server.call_tool("snaplii_purchase", args))
    return json.loads(res[0].text)


def _billpay(token=None):
    args = {"pay_code": PAY_CODE, "price": PRICE}
    if token is not None:
        args["confirmation_token"] = token
    res = asyncio.run(server.call_tool("snaplii_billpay_pay", args))
    return json.loads(res[0].text)


# ── snaplii_purchase token-binding gate ─────────────────────────────────────


def test_purchase_valid_token_charges_once_then_replay_rejected(monkeypatch):
    store, client, _ = _wire(monkeypatch)
    token = store.issue(ITEM, PRICE, {"brand": "X", "you_pay": PRICE})

    out = _purchase(token)
    assert out["orderNo"] == "ORD-1"
    assert len(client.charges) == 1
    assert client.charges[0]["payment_method"] == "SNAPLII_CREDIT"

    # Replay with the same (now consumed) token: rejected, no second charge.
    out2 = _purchase(token)
    assert out2["error"] == "confirmation_invalid"
    assert len(client.charges) == 1


def test_purchase_missing_token_rejected(monkeypatch):
    store, client, _ = _wire(monkeypatch)
    out = _purchase()  # no confirmation_token
    assert out["error"] == "confirmation_required"
    assert len(client.charges) == 0


def test_purchase_expired_token_not_charged(monkeypatch):
    clock = FakeClock()
    store, client, _ = _wire(monkeypatch, clock=clock)
    token = store.issue(ITEM, PRICE, {"brand": "X", "you_pay": PRICE})

    clock.advance(301)  # past the 300s TTL, before the purchase call
    out = _purchase(token)
    assert out["error"] == "confirmation_invalid"
    assert "expired" in out["message"]
    assert len(client.charges) == 0


def test_purchase_item_mismatch_not_charged(monkeypatch):
    store, client, _ = _wire(monkeypatch)
    # Token issued for a DIFFERENT item; purchasing ITEM must be rejected.
    token = store.issue("OTHER-ITEM", PRICE, {"brand": "X", "you_pay": PRICE})

    out = _purchase(token)
    assert out["error"] == "confirmation_invalid"
    assert len(client.charges) == 0


def test_purchase_replays_approved_context_not_defaults(monkeypatch):
    # A quote issued with a non-default voucher/cashback context must charge
    # under THAT context, not the BEST_FIT/USE hardcoded defaults.
    store, client, _ = _wire(monkeypatch)
    token = store.issue(
        ITEM, PRICE, {"brand": "X", "you_pay": PRICE},
        context={"voucher_option": "NOT_USE", "cashback_option": "NOT_USE",
                 "specified_voucher": "V-9"},
    )

    out = _purchase(token)
    assert out["orderNo"] == "ORD-1"
    assert client.last_kwargs["specified_voucher"] == "V-9"
    assert client.last_kwargs["cashback_option"] == "NOT_USE"
    assert client.last_kwargs["voucher_option"] == "NOT_USE"
    assert client.last_kwargs["payment_method"] == "SNAPLII_CREDIT"


# ── snaplii_billpay_pay token-binding gate (shares _enforce_confirmation) ────


def test_billpay_valid_token_charges_once_then_replay_rejected(monkeypatch):
    store, client, _ = _wire(monkeypatch)
    token = store.issue(PAY_CODE, PRICE, {"brand": "bill payment", "you_pay": PRICE})

    out = _billpay(token)
    assert out["orderNo"] == "B-1"
    assert out["paymentNo"] == "P-1"
    assert out["orderStatus"] == "SUCCESS"
    assert out["result"] == "Bill paid successfully from Snaplii Cash."
    assert len(client.billpay_charges) == 1

    # Replay with the same (now consumed) token: rejected, no second charge.
    out2 = _billpay(token)
    assert out2["error"] == "confirmation_invalid"
    assert len(client.billpay_charges) == 1


def test_billpay_missing_token_rejected(monkeypatch):
    store, client, _ = _wire(monkeypatch)
    out = _billpay()  # no confirmation_token
    assert out["error"] == "confirmation_required"
    assert len(client.billpay_charges) == 0


def test_billpay_expired_token_not_charged(monkeypatch):
    clock = FakeClock()
    store, client, _ = _wire(monkeypatch, clock=clock)
    token = store.issue(PAY_CODE, PRICE, {"brand": "bill payment", "you_pay": PRICE})

    clock.advance(301)
    out = _billpay(token)
    assert out["error"] == "confirmation_invalid"
    assert "expired" in out["message"]
    assert len(client.billpay_charges) == 0


def test_billpay_item_mismatch_not_charged(monkeypatch):
    store, client, _ = _wire(monkeypatch)
    token = store.issue("OTHER-CODE", PRICE, {"brand": "bill payment", "you_pay": PRICE})

    out = _billpay(token)
    assert out["error"] == "confirmation_invalid"
    assert len(client.billpay_charges) == 0


def test_billpay_replays_approved_voucher_not_default(monkeypatch):
    # billpay quote only exposes voucher_id; the charge must replay it.
    store, client, _ = _wire(monkeypatch)
    token = store.issue(
        PAY_CODE, PRICE, {"brand": "bill payment", "you_pay": PRICE},
        context={"specified_voucher": "V-9"},
    )

    out = _billpay(token)
    assert out["orderNo"] == "B-1"
    assert client.last_kwargs["specified_voucher"] == "V-9"
