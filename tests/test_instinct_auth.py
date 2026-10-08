import asyncio
import json

import keyring
import pytest
from keyring.backends.fail import Keyring

from snaplii import auth
from snaplii.client import GatewayClient
from snaplii.config_store import ConfigStore
from test_business_auth_gate import OPERATIONS


def test_prefix_variable_selects_instinct(monkeypatch):
    monkeypatch.setenv("INSTINCT_REGION", "")
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    assert auth.instinct_environment_status() == {
        "detected": True, "reason_code": "instinct_env_present",
        "env_names": ["INSTINCT_AGENT_ID", "INSTINCT_REGION"],
    }
    assert auth.detect_instinct() is True


def test_other_names_do_not_select_instinct(monkeypatch):
    monkeypatch.setenv("MY_INSTINCT_FLAG", "1")
    monkeypatch.setenv("instinct_lowercase", "1")
    assert auth.instinct_environment_status() == {
        "detected": False, "reason_code": "instinct_env_absent", "env_names": [],
    }
    assert auth.detect_instinct() is False


def test_muse_takes_precedence(monkeypatch, muse_filesystem):
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    status = auth.instinct_environment_status()
    assert status == {"detected": False, "reason_code": "muse_takes_precedence",
                      "env_names": ["INSTINCT_AGENT_ID"]}


def test_explicit_environment_returns_sorted_names_only():
    names = auth.instinct_env_names({"INSTINCT_B": "secret", "INSTINCT_A": "x", "OTHER": "y"})
    assert names == ["INSTINCT_A", "INSTINCT_B"]


@pytest.mark.parametrize("base_url,entry", [
    ("https://aipayment.snaplii.com", "Snaplii API Key"),
    ("https://aipayment.snaplii.com/", "Snaplii API Key"),
    ("https://aipay.stage.snaplii.com", "Snaplii API Key aipay.stage.snaplii.com"),
    ("http://localhost:8080", "Snaplii API Key localhost:8080"),
    ("https://aipayment.snaplii.com/gw", "Snaplii API Key aipayment.snaplii.com"),
])
def test_vault_entry_names(base_url, entry):
    assert auth.instinct_vault_entry(base_url) == entry


def test_instruction_covers_the_vault_flow_without_raw_key_entry():
    text = " ".join(auth.INSTINCT_AUTH_INSTRUCTION.split())
    for phrase in (
        "snaplii_connect", "vault_entry", "eid", "Connect", "2 minutes",
        "More → Payment Methods → AI Payment Management → + New API Key",
        "encrypted submission link", "has_valid_token=true", "never call snaplii_init",
        "Do not connect at the start of unrelated conversations",
    ):
        assert phrase in text
    assert "paste their Snaplii API key" not in text


INSTINCT_ACTION = {"type": "call_mcp_tool", "tool": "snaplii_connect", "arguments": {},
                   "instruction": auth.INSTINCT_AUTH_INSTRUCTION}


@pytest.fixture
def instinct_store(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    return ConfigStore(tmp_path / "config.json", runtime="mcp")


def test_status_reports_instinct_host_and_names_without_values(instinct_store):
    state = instinct_store.auth_status(origin=auth.DEFAULT_ORIGIN)
    assert state["host"] == "instinct"
    assert state["instinct_env"] == ["INSTINCT_AGENT_ID"]
    assert state["next_action"] == INSTINCT_ACTION
    assert "synthetic-value" not in json.dumps(state)


def test_non_instinct_status_has_no_instinct_field(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    state = ConfigStore(tmp_path / "config.json", runtime="mcp").auth_status(origin=auth.DEFAULT_ORIGIN)
    assert state["host"] == "unknown"
    assert "instinct_env" not in state


def test_muse_host_wins_over_instinct_variables(tmp_path, monkeypatch, muse_filesystem):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    state = ConfigStore(tmp_path / "config.json", runtime="cli").auth_status(origin=auth.DEFAULT_ORIGIN)
    assert state["host"] == "muse"
    assert state["next_action"]["argv"][-1] == "--vault-auth"
    assert "instinct_env" not in state


@pytest.mark.parametrize("state", [
    "auth_required", "reauth_required", "credential_required", "invalid_key",
    "credential_lookup_failed", "secure_entry_unavailable", "mcp_required",
])
@pytest.mark.parametrize("origin", [auth.DEFAULT_ORIGIN, "https://aipay.stage.snaplii.com"])
def test_instinct_actions_point_to_connect_on_any_gateway(state, origin):
    assert auth.build_auth_action(state, host="instinct", origin=origin) == INSTINCT_ACTION


@pytest.mark.parametrize("state,expected", [
    ("ready", None),
    ("cancelled", {"type": "stop", "reason": "cancelled"}),
    ("session_cache_failed", {"type": "stop", "reason": "session_cache_failed"}),
    ("temporary_gateway_error", {"type": "retry_auth_later", "reason": "temporary_gateway_error"}),
])
def test_instinct_keeps_terminal_and_retry_actions(state, expected):
    assert auth.build_auth_action(state, host="instinct") == expected


@pytest.mark.parametrize("command,name,arguments", OPERATIONS, ids=[op[1] for op in OPERATIONS])
def test_mcp_business_tools_without_session_point_to_connect(
    instinct_store, monkeypatch, httpx_mock, command, name, arguments,
):
    import server
    client = GatewayClient(auth.DEFAULT_ORIGIN, instinct_store)
    monkeypatch.setattr(server, "_get_client", lambda: client)
    monkeypatch.setattr(server, "ConfigStore", lambda: instinct_store)
    monkeypatch.setattr(server, "_base_url", lambda: auth.DEFAULT_ORIGIN)
    monkeypatch.setattr(server, "_update_notice", lambda: None)
    result = json.loads(asyncio.run(server.call_tool("snaplii_" + name, arguments))[0].text)
    client._http.close()
    assert result["auth_state"] == "auth_required"
    assert result["next_action"] == INSTINCT_ACTION
    assert httpx_mock.get_requests() == []
