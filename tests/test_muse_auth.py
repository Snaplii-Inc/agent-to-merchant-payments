import json
import stat

import pytest

from snaplii import auth
from snaplii.client import GatewayClient
from snaplii.config_store import ConfigStore
from snaplii.exceptions import ConfigError


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
    # Test injection ONLY: production detection remains closed pending T1/G1.
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
