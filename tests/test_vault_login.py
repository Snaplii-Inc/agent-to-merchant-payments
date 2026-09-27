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
import keyring
from keyring.backends.fail import Keyring
from snaplii.config_store import ConfigStore

import snaplii.cli as cli
from snaplii.client import GatewayClient
from snaplii.exceptions import GatewayApiError
from snaplii.exceptions import AuthError, ConfigError


@pytest.fixture
def vault_client(monkeypatch, tmp_path):
    helper = types.ModuleType("dynamic_credentials")
    helper.DynamicCredentialError = type("DynamicCredentialError", (Exception,), {})
    helper.add_surrogate_to_request = Mock()
    monkeypatch.setitem(sys.modules, "synthetic_muse_helper", helper)
    (tmp_path / "dynamic_credentials.py").write_text(
        "from synthetic_muse_helper import DynamicCredentialError, add_surrogate_to_request\n")
    monkeypatch.setenv("SNAPLII_VAULT_HELPER_PATH", str(tmp_path))
    # Isolate path mutations, but also check that authentication cleans them up.
    monkeypatch.setattr(sys, "path", sys.path.copy())
    original_path = sys.path.copy()
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    # No keyring in these tests: the CLI runtime needs the explicit file opt-in
    # to keep a session for a later process.
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store = ConfigStore(tmp_path / "config.json")
    client = GatewayClient("https://aipayment.snaplii.com", store)
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
            "https://aipayment.snaplii.com/v2/auth/token", status, "Gateway error", {}, response,
        )
        opener = Mock(side_effect=error)
    else:
        opener = Mock(return_value=response)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", opener)
    return opener


def _cli_error(capsys):
    with pytest.raises(SystemExit) as exc:
        cli._cli()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    return json.loads(captured.err)


def test_muse_lookup_failure_requests_native_inspection_not_blind_key_collection(vault_client, monkeypatch, muse_filesystem, capsys):
    from snaplii import auth

    # Recreate the store's environment observation through the real detector.
    vault_client._config._muse = auth.detect_muse()
    helper = sys.modules["synthetic_muse_helper"]
    helper.add_surrogate_to_request.side_effect = RuntimeError("unknown synthetic-secret")
    out = _cli_error(capsys)
    assert out["auth_state"] == "credential_lookup_failed"
    assert out["next_action"]["operation"] == "inspect_api_key"
    assert out["next_action"]["after_success"]["argv"][-1] == "--vault-auth"
    assert "synthetic-secret" not in json.dumps(out)
    assert vault_client._config.get_cached_token() is None


@pytest.mark.parametrize("reason", [
    socket.gaierror("Name resolution failed"),
    ConnectionRefusedError("Connection refused"),
    ssl.SSLError("Certificate verification failed"),
], ids=["dns", "connection-refused", "tls"])
def test_vault_transport_failure_is_structured_json(
    vault_client, monkeypatch, capsys, reason,
):
    error = urllib.error.URLError(reason)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", Mock(side_effect=error))
    out = _cli_error(capsys)
    assert out["auth_state"] == "temporary_gateway_error"
    assert out["reason_code"] == "auth_transport_failed"
    assert out["next_action"]["type"] == "retry_auth_later"
    assert str(error) not in json.dumps(out)
    assert vault_client._config.get_cached_token() is None
    assert vault_client._config.get("agent_id") is None


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
    assert vault_client._config.get_cached_token() is None
    assert vault_client._config.get("agent_id") is None


@pytest.mark.parametrize("status", [200, 403, 422])
def test_vault_deactivated_key_has_friendly_message(
    vault_client, monkeypatch, capsys, status,
):
    _mock_response(monkeypatch, status, b'{"rspMsgCd": "MCA20102"}')
    out = _cli_error(capsys)
    assert out["error"] == "This API key has been deactivated."
    assert out["error_code"] == "MCA20102"
    assert out["endpoint"] == "/v2/auth/token"
    assert out["auth_state"] == "invalid_key"
    assert vault_client._config.get_cached_token() is None
    assert vault_client._config.get("agent_id") is None


def test_vault_success_caches_token_and_country(vault_client, monkeypatch):
    body = {"access_token": "jwt-1", "expires_in": 600, "country": "us"}
    opener = _mock_response(monkeypatch, 200, json.dumps(body).encode())
    assert vault_client.login_via_vault("agent-1") == body
    assert vault_client._config.get_cached_token() == "jwt-1"
    assert vault_client.auth_status()["country"] == "US"
    request = opener.call_args.args[0]
    assert json.loads(request.data) == {"agent_id": "agent-1"}
    sys.modules["synthetic_muse_helper"].add_surrogate_to_request.assert_called_once_with(
        request, "custom.snaplii", allowed_hosts=("aipayment.snaplii.com",),
    )


def test_vault_success_without_token_is_rejected(vault_client, monkeypatch):
    _mock_response(monkeypatch, 200, b'{}')
    with pytest.raises(GatewayApiError) as exc:
        vault_client.login_via_vault("agent-1")
    assert "did not return an access token" in exc.value.to_dict()["error"]
    assert vault_client._config.get_cached_token() is None


def test_vault_missing_helper_preserves_config_and_import_path(
    vault_client, monkeypatch, capsys,
):
    monkeypatch.setenv("SNAPLII_VAULT_HELPER_PATH", "/missing/synthetic-helper")
    out = _cli_error(capsys)
    assert out["error"] == "Configuration error"
    assert out["reason_code"] == "credential_helper_unavailable"
    assert vault_client._config.get("agent_id") is None
    assert vault_client._config.get_cached_token() is None


def test_vault_credential_failure_preserves_config_and_import_path(
    vault_client, capsys,
):
    helper = sys.modules["synthetic_muse_helper"]
    helper.add_surrogate_to_request.side_effect = helper.DynamicCredentialError(
        "Credential not found")
    out = _cli_error(capsys)
    assert out["error"] == "Configuration error"
    assert out["reason_code"] == "credential_helper_failed"
    assert "Credential not found" not in json.dumps(out)
    assert vault_client._config.get("agent_id") is None
    assert vault_client._config.get_cached_token() is None


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

    cli._cli()
    assert vault_client._config.get("agent_id") == "agent-1"
    assert vault_client._config.get_cached_token() == "jwt-1"
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "authenticated"
    assert out["agent_id"] == "agent-1"


@pytest.mark.parametrize("url", [
    "http://localhost:8080", "https://aipayment.snaplii.com.evil.example",
    "https://aipayment.snaplii.com:444", "https://aipayment.snaplii.com/prefix",
    "https://aipay.stage.snaplii.com",
])
def test_vault_rejects_origin_before_loading_credentials(vault_client, url, monkeypatch):
    monkeypatch.setitem(sys.modules, "dynamic_credentials", None)
    client = GatewayClient(url, vault_client._config)
    with pytest.raises(ConfigError, match="production HTTPS origin"):
        client.login_via_vault("agent-1")


def test_helper_error_is_secret_free(vault_client, capsys):
    helper = sys.modules["synthetic_muse_helper"]
    helper.add_surrogate_to_request.side_effect = helper.DynamicCredentialError("hsurr:synthetic-secret")
    out = _cli_error(capsys)
    assert "synthetic-secret" not in json.dumps(out)
    assert out["auth_state"] == "secure_entry_unavailable"
    assert out["next_action"]["requires_user_choice"] is True


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_vault_redirect_is_not_a_success(vault_client, monkeypatch, status):
    _mock_response(monkeypatch, status, b'{"access_token":"redirected-token"}')
    with pytest.raises(AuthError) as exc:
        vault_client.login_via_vault("agent-1")
    assert exc.value.reason_code == "credential_redirect_blocked"
    assert vault_client._config.get_cached_token() is None


def test_helper_cannot_retarget_credential_request(vault_client, monkeypatch):
    helper = sys.modules["synthetic_muse_helper"]

    def retarget(request, *args, **kwargs):
        request.full_url = "https://evil.example/v2/auth/token"

    helper.add_surrogate_to_request.side_effect = retarget
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda *a, **kw: pytest.fail("must not send credential"))
    with pytest.raises(AuthError) as exc:
        vault_client.login_via_vault("agent-1")
    assert exc.value.reason_code == "credential_request_modified"


def test_helper_module_cache_does_not_override_explicit_file(vault_client, monkeypatch):
    polluted = types.ModuleType("dynamic_credentials")
    polluted.add_surrogate_to_request = lambda *a, **kw: pytest.fail("loaded polluted module")
    monkeypatch.setitem(sys.modules, "dynamic_credentials", polluted)
    _mock_response(monkeypatch, 200, b'{"access_token":"jwt-1"}')
    vault_client.login_via_vault("agent-1")
    assert vault_client.auth_status()["has_valid_token"] is True


def test_generated_agent_id_is_reused_across_successful_initializations(vault_client, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["snaplii", "init", "--vault-auth"])
    for _ in range(2):
        _mock_response(monkeypatch, 200, b'{"access_token":"jwt-1","debug":"synthetic-secret"}')
        cli._cli()
        out = json.loads(capsys.readouterr().out)
        assert "synthetic-secret" not in json.dumps(out)
        if _ == 0:
            agent_id = out["agent_id"]
            assert agent_id.startswith("agent-") and len(agent_id) == 14
        else:
            assert out["agent_id"] == agent_id


def test_explicit_agent_id_override_wins(vault_client, monkeypatch, capsys):
    vault_client._config.set("agent_id", "previous-agent")
    _mock_response(monkeypatch, 200, b'{"access_token":"jwt-1"}')
    cli._cli()
    assert json.loads(capsys.readouterr().out)["agent_id"] == "agent-1"


def test_vault_invalid_agent_id_is_rejected_before_loading_credentials(vault_client, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["snaplii", "init", "--vault-auth", "--agent-id", "bad id"])
    opener = _mock_response(monkeypatch, 200, b'{"access_token":"jwt-1"}')
    out = _cli_error(capsys)
    assert out["message"] == "Invalid agent ID."
    opener.assert_not_called()
    sys.modules["synthetic_muse_helper"].add_surrogate_to_request.assert_not_called()


def test_cache_failure_never_reports_authenticated(vault_client, monkeypatch, capsys):
    _mock_response(monkeypatch, 200, b'{"access_token":"jwt-1"}')

    def fail_replace(*args):
        raise OSError("synthetic-secret")

    monkeypatch.setattr("os.replace", fail_replace)
    result = _cli_error(capsys)
    assert result["auth_state"] == "session_cache_failed"
    assert "synthetic-secret" not in json.dumps(result)
    assert vault_client._config.get_cached_token() is None
