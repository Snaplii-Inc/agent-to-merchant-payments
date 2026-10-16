"""Quote and purchase reject amounts outside the selected card's
denomination rules (priceStart..priceEnd) before any request, as the app does.
"""

import asyncio
import json

import pytest
from click.testing import CliRunner

import server
from snaplii.client import GatewayClient
from snaplii.commands.purchase import purchase_cmd
from snaplii.commands.quote import quote_cmd
from snaplii.exceptions import (
    AmountValidationError, AuthError, GatewayApiError, GatewayConnectionError,
    ItemCheckUnavailableError, ItemIdError,
)

# Uber Eats-shaped catalog: a VARIABLE $20–$500 template + a FIXED $10 template.
BRAND_ID = "CB0000000000264"
VARIABLE_ITEM = f"{BRAND_ID}-CT000000003682"
FIXED_ITEM = f"{BRAND_ID}-CT000000001977"

_CATALOG = {"data": {"cardBrandId": BRAND_ID, "name": "Uber Eats", "cards": [
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
        _client().validate_amount(VARIABLE_ITEM, "10")
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


def test_a_verified_card_is_returned_with_its_brand_name():
    assert _client().validate_amount(VARIABLE_ITEM, "20") == {
        "item_id": VARIABLE_ITEM, "brand_name": "Uber Eats"}


def test_the_brand_name_is_left_out_when_the_catalog_has_none():
    c = GatewayClient.__new__(GatewayClient)
    unnamed = {"data": {k: v for k, v in _CATALOG["data"].items() if k != "name"}}
    c.get_card_brand_by_id = lambda brand_id: unnamed
    assert c.validate_amount(VARIABLE_ITEM, "20") == {"item_id": VARIABLE_ITEM}


def test_a_non_numeric_price_is_left_to_the_server_once_the_card_is_verified():
    assert _client().validate_amount(VARIABLE_ITEM, "abc")["item_id"] == VARIABLE_ITEM


# ── fail closed: nothing is sent unless the card is verified ─────────────────


def _lookup_raising(error):
    c = GatewayClient.__new__(GatewayClient)

    def lookup(brand_id):
        raise error
    c.get_card_brand_by_id = lookup
    return c


@pytest.mark.parametrize("error", [
    GatewayApiError(502, {}, "/v2/card-brands/x"),
    GatewayApiError(500, {"rspMsgCd": "MACP6006"}, "/v2/card-brands/x"),
    GatewayApiError(429, {}, "/v2/card-brands/x"),
    GatewayApiError(200, {"unreadable": True}, "/v2/card-brands/x"),
    GatewayConnectionError("https://gw/v2/card-brands/x", OSError("reset")),
])
def test_an_unreadable_catalog_refuses_with_a_retry_of_the_same_command(error):
    with pytest.raises(ItemCheckUnavailableError) as ei:
        _lookup_raising(error).validate_amount(VARIABLE_ITEM, "20")
    d = ei.value.to_dict()
    assert d["error"] == "item_check_unavailable" and d["outcome"] == "not_sent"
    assert "same command once more" in d["retry_hint"] and "fails again, stop" in d["retry_hint"]
    assert "Do not change the item_id" in d["retry_hint"]


@pytest.mark.parametrize("error", [
    GatewayApiError(404, {}, "/v2/card-brands/x"),
    GatewayApiError(400, {"rspMsgCd": "MCAP2001", "rspMsgInf": "brand not found"}, "/v2/card-brands/x"),
])
def test_a_brand_the_catalog_does_not_have_is_an_invalid_item_id(error):
    with pytest.raises(ItemIdError) as ei:
        _lookup_raising(error).validate_amount(VARIABLE_ITEM, "20")
    assert not isinstance(ei.value, ItemCheckUnavailableError)
    d = ei.value.to_dict()
    assert d["error"] == "invalid_item_id" and BRAND_ID in d["message"]


def _session_rejected():
    e = GatewayApiError(401, {"friendly_message": "Session rejected."}, "/v2/card-brands/x")
    e.auth_fields = {"auth_state": "reauth_required", "reason_code": "session_rejected"}
    return e


@pytest.mark.parametrize("error", [
    _session_rejected(),
    GatewayApiError(403, {}, "/v2/card-brands/x"),
    AuthError("Authentication is required.", auth_state="auth_required",
              reason_code="no_session", next_action={}),
])
def test_an_authentication_or_permission_problem_is_reported_as_it_is(error):
    with pytest.raises(type(error)) as ei:
        _lookup_raising(error).validate_amount(VARIABLE_ITEM, "20")
    assert ei.value is error


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


@pytest.mark.parametrize("reply", [
    None,
    [],
    "unavailable",
    {"data": 7},
    {"data": "unavailable"},
    {"data": [{"cardTemplateId": "CT000000003682"}]},
    {"data": {"cardBrandId": BRAND_ID, "cards": 7}},
    {"data": {"cardBrandId": BRAND_ID, "cards": "unavailable"}},
    {"data": {"cardBrandId": BRAND_ID, "cards": {"cardTemplateId": "CT000000003682"}}},
])
def test_an_unreadable_catalog_reply_is_unverifiable_not_a_wrong_id(reply):
    c = GatewayClient.__new__(GatewayClient)
    c.get_card_brand_by_id = lambda brand_id: reply
    with pytest.raises(ItemCheckUnavailableError) as ei:
        c.validate_amount(VARIABLE_ITEM, "20")
    assert ei.value.to_dict()["error"] == "item_check_unavailable"


def test_mcp_purchase_sends_nothing_on_an_unreadable_catalog_reply(monkeypatch):
    c = _cli_client()
    c.get_card_brand_by_id = lambda brand_id: {"data": {"cardBrandId": BRAND_ID, "cards": 7}}
    monkeypatch.setattr(server, "_get_client", lambda: c)
    out = json.loads(asyncio.run(
        server.call_tool("snaplii_purchase", {"item_id": VARIABLE_ITEM, "price": "20"})
    )[0].text)
    assert out["error"] == "item_check_unavailable" and c.purchased is False


@pytest.mark.parametrize("reply", [
    {"data": {"cardBrandId": BRAND_ID, "cards": []}},
    {"data": {"cardBrandId": BRAND_ID}},
    {"data": None},
    {},
])
def test_a_brand_without_the_template_is_refused(reply):
    c = GatewayClient.__new__(GatewayClient)
    c.get_card_brand_by_id = lambda brand_id: reply
    with pytest.raises(ItemIdError) as ei:
        c.validate_amount(f"{BRAND_ID}-CT999999999999", "10")
    assert ei.value.to_dict()["error"] == "invalid_item_id"


@pytest.mark.parametrize("raise_it", [
    lambda: _client().validate_amount("CT000000003682", "20"),
    lambda: _client().validate_amount(f"{BRAND_ID}-CT999999999999", "20"),
    lambda: _client().validate_amount(VARIABLE_ITEM, "10"),
])
def test_a_refused_card_or_amount_tells_the_agent_to_rethink_and_retry(raise_it):
    with pytest.raises((ItemIdError, AmountValidationError)) as ei:
        raise_it()
    d = ei.value.to_dict()
    assert d["outcome"] == "not_sent"
    assert d["retry_hint"].startswith("Nothing was sent and nothing was charged.")
    assert "Rethink the parameters" in d["retry_hint"] and "quote and purchase again" in d["retry_hint"]
    assert "refused again, stop and tell the user" in d["retry_hint"]


def test_a_gateway_item_id_rejection_gets_the_same_retry_hint():
    d = GatewayApiError(200, {"rspMsgCd": "MCAP2107"}, "/v2/purchase").to_dict()
    assert d["error_code"] == "MCAP2107" and "outcome" not in d
    assert d["retry_hint"].startswith("The gateway refused this item_id, so nothing was charged.")
    assert "Rethink the parameters" in d["retry_hint"] and "refused again, stop and tell the user" in d["retry_hint"]


@pytest.mark.parametrize("status", [500, 502, 503])
def test_a_purchase_5xx_carrying_mcap2107_is_a_definite_rejection(status):
    # MCAP2107 rejects the item_id itself, so nothing was bought at any status.
    d = GatewayApiError(status, {"rspMsgCd": "MCAP2107"}, "/v2/purchase").to_dict()
    assert "outcome" not in d
    assert d["retry_hint"].startswith("The gateway refused this item_id, so nothing was charged.")


@pytest.mark.parametrize("body", [{"rspMsgCd": "MACP6006"}, {}, {"unreadable": True}])
def test_any_other_purchase_5xx_stays_indeterminate(body):
    d = GatewayApiError(502, body, "/v2/purchase").to_dict()
    assert d["outcome"] == "indeterminate" and "Rethink" not in d["retry_hint"]


def test_an_unreadable_purchase_reply_is_indeterminate_even_when_it_names_mcap2107():
    d = GatewayApiError(200, {"rspMsgCd": "MCAP2107", "unreadable": True}, "/v2/purchase").to_dict()
    assert d["outcome"] == "indeterminate"


def test_mcap2107_has_a_readable_message():
    body = {"rspMsgCd": "MCAP2107"}
    GatewayClient._attach_friendly_message(body, "MCAP2107")
    assert "rejected this item_id" in body["friendly_message"]


def test_cli_quote_leads_with_the_verified_card():
    c = _cli_client()
    res = CliRunner().invoke(quote_cmd, ["--item-id", VARIABLE_ITEM, "--price", "20"],
                             obj={"client": c, "config_store": _FakeStore()})
    out = json.loads(res.output)
    assert list(out)[:2] == ["item_id", "brand_name"]
    assert out["item_id"] == VARIABLE_ITEM and out["brand_name"] == "Uber Eats"


def test_mcp_quote_leads_with_the_verified_card(monkeypatch):
    c = _cli_client()
    monkeypatch.setattr(server, "_get_client", lambda: c)
    out = json.loads(asyncio.run(
        server.call_tool("snaplii_quote", {"item_id": VARIABLE_ITEM, "price": "20"})
    )[0].text)
    assert out["brand_name"] == "Uber Eats" and out["item_id"] == VARIABLE_ITEM


def test_mcp_purchase_sends_nothing_when_the_catalog_cannot_be_read(monkeypatch):
    c = _cli_client()

    def unreachable(brand_id):
        raise GatewayConnectionError("https://gw/v2/card-brands/" + brand_id, OSError("reset"))
    c.get_card_brand_by_id = unreachable
    monkeypatch.setattr(server, "_get_client", lambda: c)
    out = json.loads(asyncio.run(
        server.call_tool("snaplii_purchase", {"item_id": VARIABLE_ITEM, "price": "20"})
    )[0].text)
    assert out["error"] == "item_check_unavailable" and out["outcome"] == "not_sent"
    assert c.purchased is False


def test_cli_purchase_sends_nothing_when_the_brand_is_unknown():
    c = _cli_client()
    c.get_card_brand_by_id = lambda brand_id: {"data": None}
    res = CliRunner().invoke(purchase_cmd, ["--item-id", VARIABLE_ITEM, "--price", "20"],
                             obj={"client": c, "config_store": _FakeStore()}, catch_exceptions=True)
    assert isinstance(res.exception, ItemIdError)
    assert c.purchased is False


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
