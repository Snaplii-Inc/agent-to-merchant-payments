import asyncio
import json
import re

import keyring
import pytest
from keyring.backends.fail import Keyring

import server
from snaplii import auth
from snaplii.config_store import ConfigStore
from snaplii.exceptions import GatewayConnectionError


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


EID = "ABCDEF0123456789abcdef0123456789"


@pytest.fixture
def instinct_mcp(tmp_path, monkeypatch, instinct_env):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    store = ConfigStore(tmp_path / "config.json", runtime="mcp")
    monkeypatch.setattr(server, "ConfigStore", lambda: store)
    monkeypatch.setattr(server, "_base_url", lambda: auth.DEFAULT_ORIGIN)
    monkeypatch.setattr(server, "_elicit_url", lambda: auth.DEFAULT_ORIGIN + "/connect")
    monkeypatch.setattr(server, "_ELICIT_POLL_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(server, "_ELICIT_POLL_INTERVAL_S", 0)
    return store


class _PollClient:
    def __init__(self, token=None, error=None):
        self.token, self.error = token, error
        self.polled, self.accepted = [], None

    def poll_connect_token(self, eid):
        self.polled.append(eid)
        if self.error:
            raise self.error
        return self.token

    def accept_connect_token(self, response):
        self.accepted = response
        return response

    def auth_status(self):
        return {"has_valid_token": self.accepted is not None, "host": "instinct", "auth_method": "url"}


def _call(name, arguments):
    return json.loads(asyncio.run(server.call_tool(name, arguments))[0].text)


def _use(monkeypatch, client):
    monkeypatch.setattr(server, "_get_client", lambda: client)
    return client


def test_config_show_reports_instinct(instinct_mcp):
    state = _call("snaplii_config_show", {})
    assert state["host"] == "instinct"
    assert state["instinct_env"] == ["INSTINCT_AGENT_ID"]


def test_first_call_returns_link_entry_and_eid_without_polling(instinct_mcp, monkeypatch):
    client = _use(monkeypatch, _PollClient())
    out = _call("snaplii_connect", {})
    assert out["status"] == "open_in_browser"
    assert re.fullmatch(r"[0-9a-f]{32}", out["eid"])
    assert out["connect_url"] == f"{auth.DEFAULT_ORIGIN}/connect?eid={out['eid']}"
    assert out["vault_entry"] == "Snaplii API Key"
    assert "apikey" in out["field"]
    assert client.polled == []


def test_link_keeps_page_query_and_names_the_staging_entry(instinct_mcp, monkeypatch):
    _use(monkeypatch, _PollClient())
    monkeypatch.setattr(server, "_base_url", lambda: "https://aipay.stage.snaplii.com/gw")
    monkeypatch.setattr(server, "_elicit_url", lambda: "https://aipay.stage.snaplii.com/gw/connect?lang=en")
    out = _call("snaplii_connect", {})
    assert out["connect_url"] == f"https://aipay.stage.snaplii.com/gw/connect?lang=en&eid={out['eid']}"
    assert out["vault_entry"] == "Snaplii API Key aipay.stage.snaplii.com"


@pytest.mark.parametrize("passed", [EID, f"{auth.DEFAULT_ORIGIN}/connect?eid={EID}"], ids=["eid", "whole-url"])
def test_second_call_takes_the_parked_token(instinct_mcp, monkeypatch, passed):
    client = _use(monkeypatch, _PollClient(token={"access_token": "jwt-x", "expires_in": 1800, "country": "CA"}))
    out = _call("snaplii_connect", {"eid": passed})
    assert out["status"] == "authenticated"
    assert client.polled == [EID]
    assert client.accepted["access_token"] == "jwt-x"
    assert "jwt-x" not in json.dumps(out)


@pytest.mark.parametrize("client", [
    _PollClient(token=None),
    _PollClient(error=GatewayConnectionError("https://aipayment.snaplii.com", OSError("down"))),
], ids=["not-ready", "gateway-down"])
def test_second_call_reports_pending_without_raw_key_fallback(instinct_mcp, monkeypatch, client):
    _use(monkeypatch, client)
    out = _call("snaplii_connect", {"eid": "a" * 32})
    assert out["status"] == "pending"
    assert len(client.polled) == 2
    text = json.dumps(out).lower()
    assert "without arguments" in text
    assert "snaplii init" not in text and "paste" not in text


@pytest.mark.parametrize("eid", ["short", "z" * 32, "https://evil.example/connect?x=1", 42])
def test_invalid_eid_is_rejected_without_polling(instinct_mcp, monkeypatch, eid):
    client = _use(monkeypatch, _PollClient())
    out = _call("snaplii_connect", {"eid": eid})
    assert out["status"] == "invalid_eid"
    assert client.polled == []


def test_already_connected_short_circuits_even_with_an_eid(instinct_mcp, monkeypatch):
    instinct_mcp.commit_session("synthetic-token", 3600, agent_id="agent-1",
                                auth_method="url", token_origin=auth.DEFAULT_ORIGIN)
    client = _use(monkeypatch, _PollClient())
    out = _call("snaplii_connect", {"eid": EID})
    assert out["status"] == "already_connected"
    assert client.polled == []
