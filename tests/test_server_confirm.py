"""Purchase / bill-pay charge directly with no confirmation token. Consent is the
per-key daily limit set in the app, enforced server-side by the gateway."""

import asyncio
import json

import server


class FakeClient:
    def __init__(self):
        self.charges = []
        self.billpay_charges = []
        self.last_kwargs = None

    def validate_amount(self, item_id, price):
        return None  # in-range; real guard is exercised in test_amount_validation

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


def _wire(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(server, "_get_client", lambda: client)
    return client


def _call(tool, args):
    res = asyncio.run(server.call_tool(tool, args))
    return json.loads(res[0].text)


# ── snaplii_purchase: charges directly, no confirmation token ────────────────


def test_purchase_charges_once_without_token(monkeypatch):
    client = _wire(monkeypatch)
    out = _call("snaplii_purchase", {"item_id": ITEM, "price": PRICE})
    assert out["orderNo"] == "ORD-1"
    assert len(client.charges) == 1
    assert client.charges[0]["payment_method"] == "SNAPLII_CREDIT"


def test_purchase_defaults_voucher_and_cashback(monkeypatch):
    client = _wire(monkeypatch)
    _call("snaplii_purchase", {"item_id": ITEM, "price": PRICE})
    assert client.last_kwargs["voucher_option"] == "BEST_FIT"
    assert client.last_kwargs["cashback_option"] == "USE"


def test_purchase_passes_requested_voucher_and_cashback(monkeypatch):
    # The agent passes the same options it quoted; the charge must honour them.
    client = _wire(monkeypatch)
    out = _call("snaplii_purchase", {
        "item_id": ITEM, "price": PRICE,
        "voucher_option": "NOT_USE", "cashback_option": "NOT_USE",
        "specified_voucher": "V-9",
    })
    assert out["orderNo"] == "ORD-1"
    assert client.last_kwargs["voucher_option"] == "NOT_USE"
    assert client.last_kwargs["cashback_option"] == "NOT_USE"
    assert client.last_kwargs["specified_voucher"] == "V-9"


# ── snaplii_billpay_pay: charges directly, no confirmation token ─────────────


def test_billpay_charges_once_without_token(monkeypatch):
    client = _wire(monkeypatch)
    out = _call("snaplii_billpay_pay", {"pay_code": PAY_CODE, "price": PRICE})
    assert out["orderNo"] == "B-1"
    assert out["paymentNo"] == "P-1"
    assert out["orderStatus"] == "SUCCESS"
    assert out["result"] == "Bill paid successfully from Snaplii Cash."
    assert len(client.billpay_charges) == 1


def test_billpay_passes_voucher_id(monkeypatch):
    client = _wire(monkeypatch)
    _call("snaplii_billpay_pay", {"pay_code": PAY_CODE, "price": PRICE, "voucher_id": "V-9"})
    assert client.last_kwargs["specified_voucher"] == "V-9"
