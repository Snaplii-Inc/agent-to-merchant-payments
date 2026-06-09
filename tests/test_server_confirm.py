import asyncio

import server

from snaplii.security.quote_store import QuoteStore

from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    FormElicitationCapability,
    UrlElicitationCapability,
)


class FakeElicitResult:
    def __init__(self, action, content=None):
        self.action = action
        self.content = content or {}


class FakeSession:
    def __init__(self, result):
        self._result = result
        self.last_message = None
        self.last_schema = None

    async def elicit_form(self, message, requestedSchema):
        self.last_message = message
        self.last_schema = requestedSchema
        return self._result


def test_confirm_accept_returns_true():
    session = FakeSession(FakeElicitResult("accept", {"confirm": True}))
    canonical = {"brand": "DoorDash", "you_pay": "46.00", "order_amount": "50.00"}
    approved = asyncio.run(server._confirm_via_elicitation(session, canonical))
    assert approved is True
    assert "46.00" in session.last_message  # server-built, from canonical fields


def test_confirm_decline_returns_false():
    session = FakeSession(FakeElicitResult("decline"))
    approved = asyncio.run(server._confirm_via_elicitation(session, {"you_pay": "5"}))
    assert approved is False


def test_confirm_accept_but_unchecked_returns_false():
    session = FakeSession(FakeElicitResult("accept", {"confirm": False}))
    approved = asyncio.run(server._confirm_via_elicitation(session, {"you_pay": "5"}))
    assert approved is False


def test_caps_support_form_true_when_form_present():
    caps = ClientCapabilities(
        elicitation=ElicitationCapability(form=FormElicitationCapability())
    )
    assert server._caps_support_form(caps) is True


def test_caps_support_form_false_for_url_only():
    # url-only elicitation: elicit_form would fail, so this must NOT count.
    caps = ClientCapabilities(
        elicitation=ElicitationCapability(url=UrlElicitationCapability())
    )
    assert caps.elicitation.form is None
    assert server._caps_support_form(caps) is False


def test_caps_support_form_false_when_elicitation_absent():
    assert server._caps_support_form(ClientCapabilities()) is False
    assert server._caps_support_form(None) is False


# ── snaplii_purchase TOCTOU fix: re-validate + consume before charge ────────


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


def _wire(monkeypatch, confirm_fn, clock=None):
    """Set up the module seams and return (store, client). The store is fresh
    and issues a live token for ITEM/PRICE that the tests then drive through
    snaplii_purchase."""
    clock = clock or FakeClock()
    store = QuoteStore(ttl_seconds=300, clock=clock)
    client = FakeClient()
    monkeypatch.setattr(server, "_QUOTE_STORE", store)
    monkeypatch.setattr(server, "_current_mode", lambda: server.ELICITATION)
    monkeypatch.setattr(server, "_session", lambda: None)
    monkeypatch.setattr(server, "_get_client", lambda: client)
    monkeypatch.setattr(server, "_confirm_via_elicitation", confirm_fn)
    return store, client, clock


def _purchase(token):
    res = asyncio.run(server.call_tool(
        "snaplii_purchase",
        {"item_id": ITEM, "price": PRICE, "confirmation_token": token},
    ))
    import json
    return json.loads(res[0].text)


def test_purchase_accept_charges_once_then_replay_rejected(monkeypatch):
    async def accept(session, canonical):
        return True

    store, client, _ = _wire(monkeypatch, accept)
    token = store.issue(ITEM, PRICE, {"brand": "X", "you_pay": PRICE})

    out = _purchase(token)
    assert out["orderNo"] == "ORD-1"
    assert len(client.charges) == 1
    assert client.charges[0]["payment_method"] == "SNAPLII_CREDIT"

    # Replay with the same (now consumed) token: rejected, no second charge.
    out2 = _purchase(token)
    assert out2["error"] == "confirmation_invalid"
    assert len(client.charges) == 1


def test_purchase_expired_during_wait_not_charged(monkeypatch):
    clock = FakeClock()

    async def accept_but_expire(session, canonical):
        # Simulate the user approving after the TTL has elapsed.
        clock.advance(400)
        return True

    store, client, _ = _wire(monkeypatch, accept_but_expire, clock=clock)
    token = store.issue(ITEM, PRICE, {"brand": "X", "you_pay": PRICE})

    out = _purchase(token)
    assert out["error"] == "confirmation_invalid"
    assert "expired" in out["message"]
    assert len(client.charges) == 0


def test_purchase_decline_does_not_consume_and_can_retry(monkeypatch):
    state = {"approve": False}

    async def confirm(session, canonical):
        return state["approve"]

    store, client, _ = _wire(monkeypatch, confirm)
    token = store.issue(ITEM, PRICE, {"brand": "X", "you_pay": PRICE})

    out = _purchase(token)
    assert out["status"] == "declined"
    assert len(client.charges) == 0

    # Decline did NOT consume — the same token is still live; a later accept charges.
    state["approve"] = True
    out2 = _purchase(token)
    assert out2["orderNo"] == "ORD-1"
    assert len(client.charges) == 1


def test_purchase_replays_approved_context_not_defaults(monkeypatch):
    # A quote issued with a non-default voucher/cashback context must charge
    # under THAT context, not the BEST_FIT/USE hardcoded defaults (D2 drift).
    async def accept(session, canonical):
        return True

    store, client, _ = _wire(monkeypatch, accept)
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


# ── snaplii_billpay_pay enforcement (shares _enforce_confirmation) ──────────


def _billpay(token):
    res = asyncio.run(server.call_tool(
        "snaplii_billpay_pay",
        {"pay_code": PAY_CODE, "price": PRICE, "prov": "ON", "confirmation_token": token},
    ))
    import json
    return json.loads(res[0].text)


def test_billpay_accept_charges_once_then_replay_rejected(monkeypatch):
    async def accept(session, canonical):
        return True

    store, client, _ = _wire(monkeypatch, accept)
    token = store.issue(PAY_CODE, PRICE, {"brand": "bill payment", "you_pay": PRICE})

    out = _billpay(token)
    assert out["orderNo"] == "B-1"
    assert out["paymentNo"] == "P-1"
    assert out["orderStatus"] == "SUCCESS"
    assert out["result"] == "Bill paid successfully from Snaplii Cash."
    assert len(client.billpay_charges) == 1
    assert client.billpay_charges[0]["location_prov"] == "ON"

    # Replay with the same (now consumed) token: rejected, no second charge.
    out2 = _billpay(token)
    assert out2["error"] == "confirmation_invalid"
    assert len(client.billpay_charges) == 1


def test_billpay_expired_during_wait_not_charged(monkeypatch):
    clock = FakeClock()

    async def accept_but_expire(session, canonical):
        clock.advance(400)
        return True

    store, client, _ = _wire(monkeypatch, accept_but_expire, clock=clock)
    token = store.issue(PAY_CODE, PRICE, {"brand": "bill payment", "you_pay": PRICE})

    out = _billpay(token)
    assert out["error"] == "confirmation_invalid"
    assert "expired" in out["message"]
    assert len(client.billpay_charges) == 0


def test_billpay_decline_does_not_consume_and_can_retry(monkeypatch):
    state = {"approve": False}

    async def confirm(session, canonical):
        return state["approve"]

    store, client, _ = _wire(monkeypatch, confirm)
    token = store.issue(PAY_CODE, PRICE, {"brand": "bill payment", "you_pay": PRICE})

    out = _billpay(token)
    assert out["status"] == "declined"
    assert len(client.billpay_charges) == 0

    # Decline did NOT consume — the same token is still live; a later accept charges.
    state["approve"] = True
    out2 = _billpay(token)
    assert out2["orderNo"] == "B-1"
    assert len(client.billpay_charges) == 1


def test_billpay_missing_token_rejected(monkeypatch):
    async def accept(session, canonical):
        return True

    store, client, _ = _wire(monkeypatch, accept)
    res = asyncio.run(server.call_tool(
        "snaplii_billpay_pay",
        {"pay_code": PAY_CODE, "price": PRICE, "prov": "ON"},
    ))
    import json
    out = json.loads(res[0].text)
    assert out["error"] == "confirmation_required"
    assert len(client.billpay_charges) == 0


def test_billpay_replays_approved_voucher_not_default(monkeypatch):
    # billpay quote only exposes voucher_id; the charge must replay it.
    async def accept(session, canonical):
        return True

    store, client, _ = _wire(monkeypatch, accept)
    token = store.issue(
        PAY_CODE, PRICE, {"brand": "bill payment", "you_pay": PRICE},
        context={"specified_voucher": "V-9"},
    )

    out = _billpay(token)
    assert out["orderNo"] == "B-1"
    assert client.last_kwargs["specified_voucher"] == "V-9"
    assert client.last_kwargs["location_prov"] == "ON"


def test_elicit_api_key_returns_value_on_accept():
    session = FakeSession(FakeElicitResult("accept", {"api_key": "snp_sk_live_xyz"}))
    key = asyncio.run(server._elicit_api_key(session))
    assert key == "snp_sk_live_xyz"
    assert "never shown to the assistant" in session.last_message


def test_elicit_api_key_returns_none_on_cancel():
    session = FakeSession(FakeElicitResult("cancel"))
    key = asyncio.run(server._elicit_api_key(session))
    assert key is None
