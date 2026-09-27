import asyncio
import json
from types import SimpleNamespace

import keyring
import pytest
from keyring.backends.fail import Keyring

import server
from snaplii import auth
from snaplii.client import GatewayClient
from snaplii.config_store import ConfigStore
from snaplii.exceptions import ConfigError


@pytest.fixture
def setup_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    # The server marks its stores runtime="mcp"; the fixture's client bypasses
    # _get_client, so mark this one the same way.
    store = ConfigStore(tmp_path / "config.json", runtime="mcp")
    client = GatewayClient(auth.DEFAULT_ORIGIN, store)
    monkeypatch.setattr(server, "ConfigStore", lambda: store)
    monkeypatch.setattr(server, "_get_client", lambda: client)
    monkeypatch.setattr(server, "_base_url", lambda: auth.DEFAULT_ORIGIN)
    monkeypatch.setattr("snaplii.version_check.check_for_update", lambda *a, **kw: None)
    yield store, client
    client._http.close()


def call(name, args=None):
    return json.loads(asyncio.run(server.call_tool(name, args or {}))[0].text)


def test_mcp_status_matches_cli_store_allowlist(setup_auth):
    store, _ = setup_auth
    store.set("unknown", "synthetic-secret")
    result = call("snaplii_config_show")
    # The same configuration read by a CLI-side store (no MCP runtime).
    expected = ConfigStore(store.path).auth_status(origin=auth.DEFAULT_ORIGIN)
    # Status fields are shared; memory-backed recovery stays in this runtime.
    assert {k: v for k, v in result.items() if k != "next_action"} == {
        k: v for k, v in expected.items() if k != "next_action"}
    assert result["next_action"] == {"type": "call_mcp_tool", "tool": "snaplii_connect", "arguments": {}}
    assert expected["next_action"]["type"] == "run_cli"


@pytest.mark.parametrize("tool", ["snaplii_init", "snaplii_submit_api_key"])
def test_mcp_raw_login_uses_verified_session(setup_auth, httpx_mock, tool):
    store, _ = setup_auth
    httpx_mock.add_response(method="POST", url=auth.DEFAULT_ORIGIN + "/v2/auth/token",
                            json={"access_token": "synthetic-token", "debug": "synthetic-secret"})
    result = call(tool, {"api_key": "synthetic-key"})
    assert result["status"] == "authenticated"
    assert result["has_valid_token"] is True
    assert result["auth_method"] == "api_key"
    assert result["credential_storage"] == "process memory"
    assert "synthetic" not in json.dumps(result)


def test_mcp_init_transport_failure_is_reported_as_auth_failed(setup_auth, httpx_mock):
    import httpx

    httpx_mock.add_exception(httpx.ConnectError("connection refused"))
    result = call("snaplii_init", {"api_key": "synthetic-key"})
    assert result["error"] == "auth_failed"
    assert result["auth_state"] == "temporary_gateway_error"
    assert "connection refused" not in json.dumps(result)


def test_real_config_error_does_not_ask_for_api_key(setup_auth, monkeypatch):
    def fail():
        raise ConfigError("Cannot read configuration.")

    monkeypatch.setattr(server, "_get_client", fail)
    result = call("snaplii_balance")
    assert result["error"] == "Configuration error"
    assert "API key" not in json.dumps(result)


def test_url_login_clears_previous_identity_and_commits_method(setup_auth, monkeypatch, httpx_mock):
    store, _ = setup_auth
    store.set_many({"agent_id": "previous-agent", "country": "CA"})
    monkeypatch.setattr(server, "_connect_route", lambda: "elicit")

    async def elicit_url(**kwargs):
        return SimpleNamespace(action="accept")

    monkeypatch.setattr(server, "app", SimpleNamespace(request_context=SimpleNamespace(
        session=SimpleNamespace(elicit_url=elicit_url))))
    httpx_mock.add_response(method="GET", json={"access_token": "synthetic-token", "expires_in": 600})
    result = call("snaplii_connect")
    assert result["status"] == "authenticated"
    assert result["has_valid_token"] is True
    assert result["auth_method"] == "url"
    assert "agent_id" not in result
    assert store.get("agent_id") is None
    assert store.get("country") is None


def test_expired_memory_session_recovers_in_the_same_mcp_process(setup_auth, httpx_mock, monkeypatch):
    store, _ = setup_auth
    store.commit_session("expired-token", 3600, agent_id="agent-1", auth_method="api_key", token_origin=auth.DEFAULT_ORIGIN)
    store.set("token_expires_at", 1)
    result = call("snaplii_balance")
    assert result["auth_state"] == "reauth_required"
    assert result["next_action"] == {"type": "call_mcp_tool", "tool": "snaplii_connect", "arguments": {}}
    assert httpx_mock.get_requests() == []

    monkeypatch.setattr(server, "_connect_route", lambda: "card")
    assert call(result["next_action"]["tool"])["status"] == "card_requested"
    httpx_mock.add_response(method="POST", url=auth.DEFAULT_ORIGIN + "/v2/auth/token",
                            json={"access_token": "renewed-token", "expires_in": 600})
    assert call("snaplii_submit_api_key", {"api_key": "synthetic-key"})["has_valid_token"] is True
    httpx_mock.add_response(method="GET", url=auth.DEFAULT_ORIGIN + "/v2/balance", json={"data": {"balance": 42}})
    assert call("snaplii_balance")["balance"] == 42
    assert store.get_cached_token() == "renewed-token"


def test_rejected_memory_transfer_keeps_idempotency_and_mcp_recovery(setup_auth, httpx_mock):
    store, _ = setup_auth
    store.commit_session("rejected-token", 3600, agent_id="agent-1", auth_method="api_key", token_origin=auth.DEFAULT_ORIGIN)
    httpx_mock.add_response(status_code=401, json={"code": "UNAUTHORIZED"})
    result = call("snaplii_transfer_create", {"to_phone": "+14165550123", "amount": "10", "idempotency_key": "same-key"})
    assert result["next_action"]["tool"] == "snaplii_connect"
    assert result["idempotency_key"] == "same-key"
    assert len(httpx_mock.get_requests()) == 1


@pytest.mark.parametrize("muse", [False, True])
def test_persisted_session_recovery_keeps_its_cli_action(setup_auth, monkeypatch, muse):
    store, _ = setup_auth
    if muse:
        monkeypatch.setattr(store, "_muse", auth.MuseEnvironment(True, "test_only"))
    else:
        monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store.commit_session("expired-token", 3600, agent_id="agent-1",
                         auth_method="vault" if muse else "api_key", token_origin=auth.DEFAULT_ORIGIN)
    store.set("token_expires_at", 1)
    result = call("snaplii_balance")
    assert result["next_action"] == store.auth_status(origin=auth.DEFAULT_ORIGIN)["next_action"]
    assert result["next_action"]["type"] == "run_cli"
    if muse:
        assert result["next_action"]["argv"][-1] == "--vault-auth"


def test_mcp_transfer_with_broken_config_preserves_recovery_key(setup_auth, httpx_mock):
    import httpx

    store, _ = setup_auth
    store.commit_session("rejected-token", 3600, agent_id="agent-1", auth_method="api_key", token_origin=auth.DEFAULT_ORIGIN)

    def corrupt_config(request):
        store.path.write_text("broken synthetic-secret")
        return httpx.Response(401, json={"code": "UNAUTHORIZED"})

    httpx_mock.add_callback(corrupt_config)
    result = call("snaplii_transfer_create", {"to_phone": "+14165550123", "amount": "10", "idempotency_key": "same-key"})
    assert result["auth_state"] == "session_cache_failed"
    assert result["next_action"] == {"type": "stop", "reason": "session_cache_failed"}
    assert result["idempotency_key"] == "same-key"
    assert "synthetic-secret" not in json.dumps(result)
    assert len(httpx_mock.get_requests()) == 1
