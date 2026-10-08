import asyncio
import json

import pytest

import server
from snaplii import auth


@pytest.fixture
def instinct_env(monkeypatch):
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    monkeypatch.setattr(server, "_update_notice", lambda: None)


def _tools():
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def test_instructions_gain_instinct_section_only_in_instinct(monkeypatch):
    assert auth.INSTINCT_AUTH_INSTRUCTION not in server._server_instructions()
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    text = server._server_instructions()
    assert text.startswith(server._SERVER_INSTRUCTIONS)
    assert text.endswith(auth.INSTINCT_AUTH_INSTRUCTION)


def test_tool_list_is_unchanged_outside_instinct():
    tools = _tools()
    assert "snaplii_submit_api_key" in tools
    assert tools["snaplii_connect"].meta["ui"]["resourceUri"]
    assert tools["snaplii_connect"].inputSchema["properties"] == {}


def test_instinct_tool_list_drops_the_card_and_takes_an_eid(instinct_env):
    tools = _tools()
    assert "snaplii_submit_api_key" not in tools
    connect = tools["snaplii_connect"]
    assert connect.meta is None
    assert set(connect.inputSchema["properties"]) == {"eid"}
    assert connect.inputSchema["required"] == []
    assert "vault" in connect.description
    assert "card" not in connect.description.lower()


class _NoLoginClient:
    def login(self, *args, **kwargs):
        raise AssertionError("login must not be called in Instinct")


@pytest.mark.parametrize("tool", ["snaplii_init", "snaplii_submit_api_key"])
def test_instinct_refuses_raw_api_keys(instinct_env, monkeypatch, tool):
    monkeypatch.setattr(server, "_get_client", lambda: _NoLoginClient())
    text = asyncio.run(server.call_tool(tool, {"api_key": "snp_sk_live_SECRET123"}))[0].text
    result = json.loads(text)
    assert result["error"] == "mcp_connect_required"
    assert result["auth_state"] == "mcp_required"
    assert result["reason_code"] == "instinct_requires_vault_connect"
    assert result["next_action"] == auth.build_auth_action("mcp_required", host="instinct")
    assert "SECRET123" not in text
