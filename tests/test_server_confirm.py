"""Purchase / bill-pay charge directly with no confirmation token; the per-key daily
limit set in the app is enforced server-side by the gateway."""

import asyncio
import json
from pathlib import Path

import server
from snaplii.commands import billpay, purchase


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


# ── policy: the text gives facts; the agent decides when to ask the user ───────

ROOT = Path(__file__).resolve().parents[1]

# Wording that tells the agent whether to confirm, in either direction.
DIRECTIVES = ("proceed confidently", "do not refuse", "don't refuse", "per-transaction confirmation",
              "no confirmation is needed", "no confirmation needed", "needs no confirmation", "heavy risk warnings",
              "pre-authorized", "current-turn", "current turn", 'explicit "yes"', "explicit yes", "still ask before")
# The one gate the owner kept: the final order on a merchant site.
FINAL_ORDER = ("final order", "place order", "place it", "final merchant order")


def _without_final_order_gate(text):
    return "\n".join(line for line in text.splitlines() if not any(k in line.lower() for k in FINAL_ORDER))


def _surfaces():
    tools = {t.name: t.description for t in asyncio.run(server.list_tools())}
    return {
        "server instructions": server._SERVER_INSTRUCTIONS,
        "autopilot prompt": server._AUTOPILOT_WORKFLOW,
        "purchase tool": tools["snaplii_purchase"],
        "billpay_pay tool": tools["snaplii_billpay_pay"],
        "giftcard_detail tool": tools["snaplii_giftcard_detail"],
        "cli purchase help": purchase.purchase_cmd.help,
        "cli billpay pay help": billpay.pay_cmd.help,
        "cli skill": (ROOT / "clawhub-publish/SKILL.md").read_text(),
        "autopilot skill": (ROOT / "clawhub-autopilot/SKILL.md").read_text(),
        "README": (ROOT / "README.md").read_text(),
        "claude desktop": (ROOT / "claude-desktop/PROJECT_INSTRUCTIONS.md").read_text(),
        "plugin README": (ROOT / "clawhub-plugin/README.md").read_text(),
    }


def test_agent_text_carries_no_confirmation_directives():
    for name, text in _surfaces().items():
        body = _without_final_order_gate(text).lower()
        for phrase in DIRECTIVES:
            assert phrase.lower() not in body, (name, phrase)


FACTS = {
    "server instructions": ("prepaid", "daily limit", "revocable", "cannot be undone", "5 minutes"),
    "cli skill": ("prepaid", "daily limit", "revocable", "cannot be undone", "5 minutes"),
    "autopilot skill": ("prepaid", "daily limit"),
    "README": ("prepaid", "daily limit", "revoc", "cannot be undone", "5 minutes"),
    "claude desktop": ("prepaid", "daily limit", "cannot be undone"),
    "plugin README": ("prepaid", "daily limit", "cannot be undone", "5-minute"),
    "billpay_pay tool": ("cannot be undone",),
    "cli billpay pay help": ("cannot be undone",),
    "purchase tool": ("daily limit",),
}


def test_agent_text_states_the_facts_the_agent_judges_by():
    surfaces = _surfaces()
    for name, needles in FACTS.items():
        text = surfaces[name].lower()
        for needle in needles:
            assert needle in text, (name, needle)


def test_autopilot_keeps_its_final_order_gate():
    skill = (ROOT / "clawhub-autopilot/SKILL.md").read_text()
    assert "Place Order" in skill and 'explicit "yes"' in skill
    assert "CONFIRM (final order)" in server._AUTOPILOT_WORKFLOW
    for relative in ("skills/snaplii-autopilot.md", "clawhub-autopilot/SKILL.md"):
        assert "Confirm & buy" not in (ROOT / relative).read_text()
    assert (ROOT / "skills/snaplii-autopilot.md").read_bytes() == (ROOT / "clawhub-autopilot/SKILL.md").read_bytes()
    assert (ROOT / "skills/snaplii-cli.md").read_bytes() == (ROOT / "clawhub-publish/SKILL.md").read_bytes()
