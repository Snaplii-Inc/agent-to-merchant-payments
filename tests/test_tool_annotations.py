import asyncio

import pytest

import server

READ_ONLY = {
    "snaplii_config_show", "snaplii_balance", "snaplii_browse_tags", "snaplii_browse_brand",
    "snaplii_giftcard_list", "snaplii_giftcard_detail", "snaplii_quote", "snaplii_cashback_calc",
    "snaplii_dashboard", "snaplii_billpay_payees", "snaplii_billpay_detail",
    "snaplii_billpay_history", "snaplii_billpay_vouchers", "snaplii_billpay_quote",
    "snaplii_billpay_result", "snaplii_transfer_status", "snaplii_transfer_list",
}
# Tools that move money or undo a pending money movement.
DESTRUCTIVE = {
    "snaplii_purchase", "snaplii_billpay_pay", "snaplii_transfer_create",
    "snaplii_transfer_finish", "snaplii_transfer_cancel",
}
# Tools that change state but cannot lose anything: sign-in and saving a bill draft.
ADDITIVE = {"snaplii_init", "snaplii_connect", "snaplii_submit_api_key", "snaplii_billpay_save"}
# A repeat changes nothing: connect returns already_connected, and a cancelled or
# finished transfer stays so. A fresh sign-in replaces the session, so it is not here.
IDEMPOTENT = {"snaplii_connect", "snaplii_transfer_cancel", "snaplii_transfer_finish"}


def _tools():
    return asyncio.run(server.list_tools())


def test_every_tool_is_classified_exactly_once():
    names = {tool.name for tool in _tools()}
    assert READ_ONLY | DESTRUCTIVE | ADDITIVE == names
    assert not (READ_ONLY & DESTRUCTIVE or READ_ONLY & ADDITIVE or DESTRUCTIVE & ADDITIVE)
    assert set(server.TOOL_ANNOTATIONS) == names


def test_every_tool_has_a_title_and_hints():
    for tool in _tools():
        hints = tool.annotations
        assert hints is not None, tool.name
        assert tool.title and tool.title == hints.title, tool.name
        assert len(tool.title) <= 40, tool.name
        assert hints.readOnlyHint is (tool.name in READ_ONLY), tool.name
        if hints.readOnlyHint:
            assert hints.destructiveHint is None and hints.idempotentHint is None, tool.name
        else:
            assert hints.destructiveHint is (tool.name in DESTRUCTIVE), tool.name
            assert hints.idempotentHint is (tool.name in IDEMPOTENT), tool.name
        # Every call may reach the Snaplii service or PyPI's update check.
        assert hints.openWorldHint is True, tool.name


def test_hints_reach_the_wire():
    wire = {tool["name"]: tool for tool in
            (t.model_dump(by_alias=True, exclude_none=True) for t in _tools())}
    assert wire["snaplii_purchase"]["annotations"] == {
        "title": "Buy a gift card", "readOnlyHint": False, "destructiveHint": True,
        "idempotentHint": False, "openWorldHint": True,
    }
    assert wire["snaplii_balance"]["title"] == "Get Snaplii Cash balance"
    assert wire["snaplii_balance"]["annotations"]["readOnlyHint"] is True
    assert "destructiveHint" not in wire["snaplii_balance"]["annotations"]


def test_instinct_keeps_the_hints(monkeypatch):
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    tools = {tool.name: tool for tool in _tools()}
    assert "snaplii_init" not in tools
    assert tools["snaplii_connect"].annotations == server.TOOL_ANNOTATIONS["snaplii_connect"]
    assert tools["snaplii_purchase"].annotations.destructiveHint is True


@pytest.mark.parametrize("name", ["snaplii_submit_api_key"])
def test_card_only_tool_tells_the_model_not_to_call_it(name):
    tool = {t.name: t for t in _tools()}[name]
    assert "Do not call it yourself" in tool.description
    assert "rejects model calls" not in tool.description


def test_server_info_reports_this_package():
    from importlib.metadata import version
    options = server.app.create_initialization_options()
    assert options.server_name == "snaplii"
    assert options.server_version == version("snaplii-mcp")
    assert options.website_url == "https://www.snaplii.com/a2m/"
