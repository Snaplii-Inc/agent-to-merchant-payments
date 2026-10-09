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
from snaplii.exceptions import AmountValidationError, ItemIdError

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


def test_fails_open_on_a_non_numeric_price():
    _client().validate_amount(VARIABLE_ITEM, "abc")  # no raise — server stays authority


def test_fails_open_when_the_catalog_cannot_be_read():
    from snaplii.exceptions import GatewayApiError

    c = GatewayClient.__new__(GatewayClient)

    def unreachable(brand_id):
        raise GatewayApiError(502, {}, "/v2/card-brands/" + brand_id)
    c.get_card_brand_by_id = unreachable
    c.validate_amount(VARIABLE_ITEM, "10")  # no raise — the gateway decides


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


# ── item_id: structure checked locally; the template must belong to the brand ─
# A pair whose template belongs to another brand names a different card than the
# one the agent browsed, so it is refused before quote or purchase.


@pytest.mark.parametrize("item_id", [
    BRAND_ID, "CT000000003682", "malformed", f"{BRAND_ID}CT000000003682", f"{BRAND_ID}--CT000000003682",
    f"{VARIABLE_ITEM} ", f" {VARIABLE_ITEM}", f"{BRAND_ID}-CT000000003682-x", "",
])
def test_malformed_item_id_is_rejected_before_any_request(item_id):
    c = GatewayClient.__new__(GatewayClient)
    c.get_card_brand_by_id = lambda brand_id: pytest.fail("no catalog request for a malformed item_id")
    with pytest.raises(ItemIdError) as ei:
        c.validate_amount(item_id, "20")
    d = ei.value.to_dict()
    assert d["error"] == "invalid_item_id" and "{cardBrandId}-{cardTemplateId}" in d["message"]


def test_template_from_another_brand_is_rejected():
    with pytest.raises(ItemIdError) as ei:
        _client().validate_amount(f"{BRAND_ID}-CT999999999999", "10")
    d = ei.value.to_dict()
    assert d["error"] == "invalid_item_id" and "CT999999999999" in d["message"] and BRAND_ID in d["message"]


def test_a_brand_without_listed_cards_fails_open():
    c = GatewayClient.__new__(GatewayClient)
    c.get_card_brand_by_id = lambda brand_id: {"data": {"cardBrandId": BRAND_ID, "cards": []}}
    c.validate_amount(f"{BRAND_ID}-CT999999999999", "10")  # nothing to compare against: the gateway decides


def test_mcp_purchase_blocks_a_mismatched_item_id(monkeypatch):
    c = _cli_client()
    monkeypatch.setattr(server, "_get_client", lambda: c)
    out = json.loads(asyncio.run(
        server.call_tool("snaplii_purchase", {"item_id": f"{BRAND_ID}-CT999999999999", "price": "10"})
    )[0].text)
    assert out["error"] == "invalid_item_id"
    assert c.purchased is False


def test_cli_purchase_blocks_a_malformed_item_id():
    c = _cli_client()
    res = CliRunner().invoke(purchase_cmd, ["--item-id", "CT000000003682", "--price", "10"],
                             obj={"client": c, "config_store": _FakeStore()}, catch_exceptions=True)
    assert isinstance(res.exception, ItemIdError)
    assert c.purchased is False
