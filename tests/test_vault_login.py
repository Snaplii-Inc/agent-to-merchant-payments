"""Vault authentication must preserve the CLI's structured error handling."""

import io
import json
import socket
import ssl
import sys
import types
import urllib.error
from unittest.mock import Mock

import pytest

import snaplii.cli as cli
from snaplii.client import GatewayClient
from snaplii.exceptions import GatewayApiError


@pytest.fixture
def vault_client(monkeypatch, tmp_path):
    helper = types.ModuleType("dynamic_credentials")
    helper.DynamicCredentialError = type("DynamicCredentialError", (Exception,), {})
    helper.add_surrogate_to_request = Mock()
    monkeypatch.setitem(sys.modules, "dynamic_credentials", helper)
    monkeypatch.setenv("SNAPLII_VAULT_HELPER_PATH", str(tmp_path))
    # Isolate path mutations, but also check that authentication cleans them up.
    monkeypatch.setattr(sys, "path", sys.path.copy())
    original_path = sys.path.copy()
    store = Mock()
    store.get.side_effect = lambda key, default=None: default
    client = GatewayClient("https://gw.test", store)
    monkeypatch.setattr(cli, "ConfigStore", lambda: store)
    monkeypatch.setattr(cli, "GatewayClient", lambda *args: client)
    monkeypatch.setattr(cli, "check_for_update", lambda store: None)
    monkeypatch.setattr(sys, "argv", [
        "snaplii", "init", "--vault-auth", "--agent-id", "agent-1",
    ])
    yield client
    client._http.close()
    assert sys.path == original_path


def _mock_response(monkeypatch, status, raw):
    response = io.BytesIO(raw)
    response.status = status
    if status >= 400:
        error = urllib.error.HTTPError(
            "https://gw.test/v2/auth/token", status, "Gateway error", {}, response,
        )
        opener = Mock(side_effect=error)
    else:
        opener = Mock(return_value=response)
    monkeypatch.setattr("urllib.request.urlopen", opener)
    return opener


def _cli_error(capsys):
    with pytest.raises(SystemExit) as exc:
        cli._cli()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    return json.loads(captured.err)


@pytest.mark.parametrize("reason", [
    socket.gaierror("Name resolution failed"),
    ConnectionRefusedError("Connection refused"),
    ssl.SSLError("Certificate verification failed"),
], ids=["dns", "connection-refused", "tls"])
def test_vault_transport_failure_is_structured_json(
    vault_client, monkeypatch, capsys, reason,
):
    error = urllib.error.URLError(reason)
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=error))
    out = _cli_error(capsys)
    assert out == {
        "error": "Connection failed",
        "url": "https://gw.test/v2/auth/token",
        "cause": str(error),
    }
    vault_client._config.cache_token.assert_not_called()
    vault_client._config.set.assert_not_called()


@pytest.mark.parametrize("raw", [
    b'"upstream failure"', b'["upstream failure"]', b'null', b'upstream failure',
], ids=["json-string", "json-list", "json-null", "plain-text"])
def test_vault_non_object_error_is_structured_json(
    vault_client, monkeypatch, capsys, raw,
):
    _mock_response(monkeypatch, 500, raw)
    out = _cli_error(capsys)
    assert out["error"].startswith("Request failed (HTTP 500).")
    assert out["endpoint"] == "/v2/auth/token"
    vault_client._config.cache_token.assert_not_called()
    vault_client._config.set.assert_not_called()


@pytest.mark.parametrize("status", [200, 403, 422])
def test_vault_deactivated_key_has_friendly_message(
    vault_client, monkeypatch, capsys, status,
):
    _mock_response(monkeypatch, status, b'{"rspMsgCd": "MCA20102"}')
    out = _cli_error(capsys)
    assert out == {
        "error": "This API key has been deactivated.",
        "error_code": "MCA20102",
        "endpoint": "/v2/auth/token",
    }
    vault_client._config.cache_token.assert_not_called()
    vault_client._config.set.assert_not_called()


def test_vault_success_caches_token_and_country(vault_client, monkeypatch):
    body = {"access_token": "jwt-1", "expires_in": 600, "country": "us"}
    opener = _mock_response(monkeypatch, 200, json.dumps(body).encode())
    assert vault_client.login_via_vault("agent-1") == body
    vault_client._config.cache_token.assert_called_once_with("jwt-1", 600)
    vault_client._config.set.assert_called_once_with("country", "US")
    request = opener.call_args.args[0]
    assert json.loads(request.data) == {"agent_id": "agent-1"}
    sys.modules["dynamic_credentials"].add_surrogate_to_request.assert_called_once_with(
        request, "custom.snaplii", allowed_hosts=("gw.test",),
    )


def test_vault_success_without_token_is_rejected(vault_client, monkeypatch):
    _mock_response(monkeypatch, 200, b'{}')
    with pytest.raises(GatewayApiError) as exc:
        vault_client.login_via_vault("agent-1")
    assert "did not return an access token" in exc.value.to_dict()["error"]
    vault_client._config.cache_token.assert_not_called()


def test_vault_missing_helper_preserves_config_and_import_path(
    vault_client, monkeypatch, capsys,
):
    monkeypatch.setitem(sys.modules, "dynamic_credentials", None)
    out = _cli_error(capsys)
    assert out["error"] == "Configuration error"
    assert "dynamic_credentials helper" in out["message"]
    vault_client._config.set.assert_not_called()
    vault_client._config.cache_token.assert_not_called()


def test_vault_credential_failure_preserves_config_and_import_path(
    vault_client, capsys,
):
    helper = sys.modules["dynamic_credentials"]
    helper.add_surrogate_to_request.side_effect = helper.DynamicCredentialError(
        "Credential not found")
    out = _cli_error(capsys)
    assert out["error"] == "Configuration error"
    assert "Credential not found" in out["message"]
    vault_client._config.set.assert_not_called()
    vault_client._config.cache_token.assert_not_called()


def test_vault_preserves_helper_path_already_present(
    vault_client, monkeypatch, tmp_path,
):
    existing_path = [*sys.path, str(tmp_path)]
    with monkeypatch.context() as patch:
        patch.setattr(sys, "path", existing_path.copy())
        _mock_response(patch, 200, b'{"access_token": "jwt-1"}')
        vault_client.login_via_vault("agent-1")
        assert sys.path == existing_path


def test_vault_init_saves_agent_id_only_after_success(
    vault_client, monkeypatch, capsys,
):
    _mock_response(monkeypatch, 200, b'{"access_token": "jwt-1"}')

    def check_token_already_cached(key, value):
        assert (key, value) == ("agent_id", "agent-1")
        vault_client._config.cache_token.assert_called_once_with("jwt-1", 3600)

    vault_client._config.set.side_effect = check_token_already_cached
    cli._cli()
    vault_client._config.set.assert_called_once_with("agent_id", "agent-1")
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "authenticated"
    assert out["agent_id"] == "agent-1"
