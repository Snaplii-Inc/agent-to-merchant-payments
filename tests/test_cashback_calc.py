"""Browse and both cashback calculators read a card's cashback the same way."""
import asyncio
import json

import pytest
from click.testing import CliRunner

import server
from snaplii.client import summarize_denominations
from snaplii.commands.smart import cashback_cmd


def _brand(wrapped, **cashback):
    card = {"cardTemplateId": "T50", "faceValueRules": {"type": "FIXED", "priceStart": "50"}, **cashback}
    brand = {"cardBrandId": "CB1", "cards": [card]}
    return {"data": brand} if wrapped else brand


class _Client:
    def __init__(self, detail):
        self.detail = detail

    def get_card_brand_by_id(self, brand_id):
        return self.detail


CASES = [({"regularDiscount": "10"}, "10"), ({"discount": "5", "regularDiscount": "10"}, "5")]


@pytest.mark.parametrize("wrapped", [True, False], ids=["data-wrapped", "direct"])
@pytest.mark.parametrize("cashback,pct", CASES, ids=["regular-only", "discount-first"])
def test_mcp_cashback_matches_browse(monkeypatch, wrapped, cashback, pct):
    detail = _brand(wrapped, **cashback)
    assert summarize_denominations(detail)[0]["cashback_percent"] == pct
    monkeypatch.setattr(server, "_get_client", lambda: _Client(detail))
    res = asyncio.run(server.call_tool("snaplii_cashback_calc", {"brand_id": "CB1", "amount": 50}))
    out = json.loads(res[0].text)
    assert out["cashback"] == f"{float(pct)}%"
    assert out["you_save"] == f"${50 * float(pct) / 100:.2f}"


@pytest.mark.parametrize("wrapped", [True, False], ids=["data-wrapped", "direct"])
@pytest.mark.parametrize("cashback,pct", CASES, ids=["regular-only", "discount-first"])
def test_cli_cashback_matches_browse(wrapped, cashback, pct):
    detail = _brand(wrapped, **cashback)
    res = CliRunner().invoke(cashback_cmd, ["--brand-id", "CB1", "--amount", "50"],
                             obj={"client": _Client(detail)})
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert out["cashback_percent"] == f"{float(pct)}%"
    assert out["you_save"] == f"${50 * float(pct) / 100:.2f}"
