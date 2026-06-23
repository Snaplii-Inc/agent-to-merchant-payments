"""Regression: out-of-range gift-card amounts must be rejected client-side
before quote/purchase.

The app UI (DrawerBottomInputAmount) blocks amounts outside a card's
priceStart..priceEnd, but the agent path (CLI/MCP) bypassed it: the backend
accepted e.g. Uber Eats $10 on a $20-min card, returned you_pay=0, charged
Snaplii Cash, then failed the card (APPLY_REFUND). validate_amount restores the
same guard so an out-of-range order never reaches quote or purchase.
"""

import asyncio
import json

import pytest
from click.testing import CliRunner

import server
from snaplii.client import GatewayClient
from snaplii.commands.purchase import purchase_cmd
from snaplii.commands.quote import quote_cmd
from snaplii.exceptions import AmountValidationError

# Uber Eats-shaped catalog: a VARIABLE $20–$500 template + a FIXED $10 template.
BRAND_ID = "CB0000000000264"
VARIABLE_ITEM = f"{BRAND_ID}-CT000000003682"
FIXED_ITEM = f"{BRAND_ID}-CT000000001977"

_CATALOG = {"data": {"cardBrandId": BRAND_ID, "cards": [
    {"cardTemplateId": "CT000000003682",
     "faceValueRules": {"type": "VARIABLE", "priceStart": "20", "priceEnd": "500"}},
    {"cardTemplateId": "CT000000001977",
     "faceValueRules": {"type": "FIXED", "priceStart": "10"}},
]}}


def _client():
    """A GatewayClient with the catalog stubbed (no network, no config)."""
    c = GatewayClient.__new__(GatewayClient)
    c.get_card_brand_by_id = lambda brand_id: _CATALOG
    return c


# ── validate_amount unit behaviour ──────────────────────────────────────────


def test_variable_below_min_blocked():
    with pytest.raises(AmountValidationError) as ei:
        _client().validate_amount(VARIABLE_ITEM, "10")  # the actual incident
    d = ei.value.to_dict()
    assert d["error"] == "amount_out_of_range"
    assert d["min_amount"] == 20.0 and d["max_amount"] == 500.0


def test_variable_above_max_blocked():
    with pytest.raises(AmountValidationError):
        _client().validate_amount(VARIABLE_ITEM, "600")


@pytest.mark.parametrize("price", ["20", "250", "500"])
def test_variable_in_range_ok(price):
    _client().validate_amount(VARIABLE_ITEM, price)  # no raise


def test_fixed_exact_ok():
    _client().validate_amount(FIXED_ITEM, "10")  # no raise


def test_fixed_mismatch_blocked():
    with pytest.raises(AmountValidationError) as ei:
        _client().validate_amount(FIXED_ITEM, "15")
    assert ei.value.to_dict()["fixed_amount"] == 10.0


# ── fail-open: never block when the catalog can't be resolved ────────────────


@pytest.mark.parametrize("item_id,price", [
    (f"{BRAND_ID}-CT999999999999", "10"),  # unknown template
    ("malformed", "10"),                   # unparseable item id
    (VARIABLE_ITEM, "abc"),                # non-numeric price
])
def test_fails_open(item_id, price):
    _client().validate_amount(item_id, price)  # no raise — server stays authority


# ── the guard is actually wired into the CLI + MCP entry points ──────────────


class _FakeStore:
    def get(self, key, default=None):
        return default


def _cli_client():
    c = _client()
    c.quoted = c.purchased = False

    def quote_order(**kwargs):
        c.quoted = True
        return {"orderAmount": "10", "primaryPayAmount": "0"}

    def create_order_and_pay(**kwargs):
        c.purchased = True
        return {"orderNo": "ORD-1", "status": "SUCCESS"}

    c.quote_order = quote_order
    c.create_order_and_pay = create_order_and_pay
    return c


def test_cli_quote_blocks_out_of_range():
    c = _cli_client()
    res = CliRunner().invoke(quote_cmd, ["--item-id", VARIABLE_ITEM, "--price", "10"],
                             obj={"client": c, "config_store": _FakeStore()},
                             catch_exceptions=True)
    assert isinstance(res.exception, AmountValidationError)
    assert c.quoted is False  # never reached the quote call


def test_cli_purchase_blocks_out_of_range():
    c = _cli_client()
    res = CliRunner().invoke(purchase_cmd, ["--item-id", VARIABLE_ITEM, "--price", "10"],
                             obj={"client": c, "config_store": _FakeStore()},
                             catch_exceptions=True)
    assert isinstance(res.exception, AmountValidationError)
    assert c.purchased is False  # Snaplii Cash never debited


def test_mcp_purchase_blocks_out_of_range(monkeypatch):
    c = _cli_client()
    monkeypatch.setattr(server, "_get_client", lambda: c)
    out = json.loads(asyncio.run(
        server.call_tool("snaplii_purchase", {"item_id": VARIABLE_ITEM, "price": "10"})
    )[0].text)
    assert out["error"] == "amount_out_of_range"
    assert c.purchased is False


def test_mcp_quote_blocks_out_of_range(monkeypatch):
    c = _cli_client()
    monkeypatch.setattr(server, "_get_client", lambda: c)
    out = json.loads(asyncio.run(
        server.call_tool("snaplii_quote", {"item_id": VARIABLE_ITEM, "price": "10"})
    )[0].text)
    assert out["error"] == "amount_out_of_range"
    assert c.quoted is False
