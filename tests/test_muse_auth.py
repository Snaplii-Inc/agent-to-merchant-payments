import json
import stat

import pytest

from snaplii import auth
from snaplii.client import GatewayClient
from snaplii.config_store import ConfigStore
from snaplii.exceptions import ConfigError
from snaplii.cli import main
from click.testing import CliRunner


def test_host_artifacts_enable_muse_file_cache_without_opt_in(tmp_path, monkeypatch, muse_filesystem):
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    store = ConfigStore(tmp_path / "config.json", runtime="cli")
    state = store.auth_status(origin=auth.DEFAULT_ORIGIN)
    assert state["host"] == "muse"
    assert state["credential_storage"] == "config file"
    assert state["next_action"]["argv"][-1] == "--vault-auth"
    store.commit_session("synthetic-token", 600, agent_id="agent-1", auth_method="vault",
                         token_origin=auth.DEFAULT_ORIGIN)
    assert ConfigStore(store.path, runtime="cli").auth_status(origin=auth.DEFAULT_ORIGIN)["has_valid_token"] is True
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


@pytest.mark.parametrize("target,mode,uid", [
    ("/opt/hatch/skills/skill-creator/bin/dynamic_credentials.py", stat.S_IFREG | 0o666, 0),
    ("/opt/hatch/skills/skill-creator/bin/dynamic_credentials.py", stat.S_IFREG | 0o644, 1000),
    ("/opt/hatch/skills/skill-creator/bin/dynamic_credentials.py", stat.S_IFLNK | 0o777, 0),
    ("/run/hatch/auth/authd.sock", stat.S_IFREG | 0o644, 0),
    ("/run/hatch/auth/authd.sock", stat.S_IFSOCK | 0o660, 1000),
    ("/run/hatch/auth", stat.S_IFDIR | 0o777, 0),
    ("/opt/hatch", stat.S_IFLNK | 0o755, 0),
])
def test_replaceable_or_wrong_type_host_artifacts_do_not_select_muse(muse_filesystem, target, mode, uid):
    muse_filesystem[target] = (mode, uid)
    assert auth.detect_muse().detected is False


def test_doctor_reports_host_and_storage_without_collecting_credentials(tmp_path, monkeypatch, muse_filesystem, httpx_mock):
    path = tmp_path / "candidate" / "config.json"
    monkeypatch.setenv("SNAPLII_CONFIG_PATH", str(path))
    result = CliRunner().invoke(main, ["config", "doctor"])
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["muse"]["detected"] is True
    assert output["authentication"]["credential_storage"] == "config file"
    assert output["authentication"]["has_valid_token"] is False
    assert not path.exists()
    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize("muse", [False, True])
@pytest.mark.parametrize("contents", ["{invalid JSON synthetic-secret", '{"base_url":"not a URL synthetic-secret"}'])
def test_doctor_config_failure_has_safe_recovery_fields(tmp_path, monkeypatch, httpx_mock, request, muse, contents):
    if muse:
        request.getfixturevalue("muse_filesystem")
    path = tmp_path / "config.json"
    path.write_text(contents)
    monkeypatch.setenv("SNAPLII_CONFIG_PATH", str(path))
    result = CliRunner().invoke(main, ["config", "doctor"])
    assert result.exit_code == 0, result.output
    status = json.loads(result.output)["authentication"]
    assert status["has_valid_token"] is False
    assert status["auth_state"] == "session_cache_failed"
    assert status["host"] == ("muse" if muse else "unknown")
    assert status["credential_storage"] == "unknown"
    assert status["auth_method"] is None
    assert status["base_url"] is None
    assert status["next_action"] == {"type": "stop", "reason": "session_cache_failed"}
    assert "synthetic-secret" not in result.output
    assert httpx_mock.get_requests() == []
    assert path.read_text() == contents


def test_muse_init_defaults_to_secure_auth_and_keeps_explicit_legacy_fallback(tmp_path, monkeypatch, muse_filesystem, httpx_mock):
    monkeypatch.setenv("SNAPLII_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setenv("SNAPLII_VAULT_HELPER_PATH", str(tmp_path / "missing-helper"))
    runner = CliRunner()
    first = runner.invoke(main, ["init"], input="synthetic-key\n")
    assert first.exit_code != 0
    error = first.exception.to_dict()
    assert error["auth_state"] == "secure_entry_unavailable"
    assert error["next_action"]["requires_user_choice"] is True
    assert error["next_action"]["argv"][-1] == "--legacy-auth"
    assert httpx_mock.get_requests() == []

    httpx_mock.add_response(method="POST", url=auth.DEFAULT_ORIGIN + "/v2/auth/token",
                            json={"access_token": "synthetic-token", "expires_in": 600})
    fallback = runner.invoke(main, ["init", "--legacy-auth"], input="synthetic-key\n")
    assert fallback.exit_code == 0, fallback.output
    state = json.loads(fallback.output)
    assert state["has_valid_token"] is True
    assert state["auth_method"] == "api_key"
    assert state["credential_storage"] == "config file"
    assert "synthetic" not in fallback.output


def test_unverified_muse_environment_cannot_enable_file_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPLII_VAULT_HELPER_PATH", str(tmp_path))
    monkeypatch.setenv("JARVIS_AUTHD_SOCK", str(tmp_path / "authd.sock"))
    monkeypatch.setenv("SNAPLII_IS_MUSE", "1")
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "0")
    assert auth.detect_muse().detected is False
    store = ConfigStore(tmp_path / "config.json")
    store._use_keyring = False
    store.commit_session("synthetic-token", 3600, agent_id="agent-1", auth_method="vault",
                         token_origin=auth.DEFAULT_ORIGIN)
    assert "access_token" not in json.loads(store.path.read_text())
    assert store.auth_status(origin=auth.DEFAULT_ORIGIN)["host"] == "unknown"


def test_verified_host_policy_selects_file_without_changing_global_policy(tmp_path, monkeypatch):
    # Isolated storage-policy test; host metadata detection is exercised above.
    monkeypatch.setattr(auth, "detect_muse", lambda: auth.MuseEnvironment(True, "test_only"))
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    store = ConfigStore(tmp_path / "private" / "config.json")
    store.commit_session("synthetic-token", 604800, agent_id="agent-1", auth_method="vault",
                         token_origin=auth.DEFAULT_ORIGIN)
    assert ConfigStore(store.path).get_cached_token() == "synthetic-token"
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700
    assert "allow_insecure_mode" not in store.load()
    store.clear_token()
    state = store.auth_status(origin=auth.DEFAULT_ORIGIN)
    assert state["next_action"]["argv"] == ["snaplii", "--base-url", auth.DEFAULT_ORIGIN, "init", "--vault-auth"]
    assert state["credential_storage"] == "config file"


@pytest.mark.parametrize("url", [
    "http://evil.example/localhost", "http://evil127.0.0.1.example",
    "https://user:synthetic-key@aipayment.snaplii.com", "https://aipayment.snaplii.com?key=synthetic-key",
    "https://aipayment.snaplii.com#key", "https://aipayment.snaplii.com:bad",
    "https://aipayment.snaplii.com\\@evil.example",
])
def test_gateway_url_rejects_ambiguous_or_secret_bearing_urls(tmp_path, url):
    with pytest.raises(ConfigError) as exc:
        GatewayClient(url, ConfigStore(tmp_path / "config.json"))
    assert "synthetic-key" not in str(exc.value)


@pytest.mark.parametrize("state", ["cancelled", "permission_denied"])
def test_cancellation_and_denial_never_fall_back_or_retry(state):
    action = auth.build_auth_action(state, host="muse")
    assert action == {"type": "stop", "reason": state}
