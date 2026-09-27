import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import keyring
import pytest
from keyring.backends import chainer, fail, null

from snaplii import config_store
from snaplii.config_store import ConfigStore
from snaplii.exceptions import AuthError, ConfigError

ORIGIN = "https://aipayment.snaplii.com"


class MemoryKeyring:
    priority = 1

    def __init__(self):
        self.values = {}
        self.write_mode = "ok"

    def get_password(self, service, key):
        return self.values.get((service, key))

    def set_password(self, service, key, value):
        if self.write_mode == "raise":
            raise RuntimeError("synthetic-keyring-secret")
        if self.write_mode == "ok":
            self.values[service, key] = value

    def delete_password(self, service, key):
        self.values.pop((service, key), None)


@pytest.fixture
def fake_keyring(monkeypatch):
    backend = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    for name in ("set_password", "get_password", "delete_password"):
        monkeypatch.setattr(keyring, name, getattr(backend, name))
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    return backend


@pytest.mark.parametrize("mode", ["raise", "discard"])
@pytest.mark.parametrize("persist", [False, True])
def test_runtime_keyring_failure_falls_back_without_resurrecting_old_token(
    tmp_path, monkeypatch, fake_keyring, mode, persist
):
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1" if persist else "0")
    path = tmp_path / "config.json"
    first = ConfigStore(path)
    first.cache_token("old-token", 3600)
    fake_keyring.write_mode = mode
    first.cache_token("new-token", 3600)

    assert ConfigStore(path).get_cached_token() == "new-token"
    assert ("access_token" in json.loads(path.read_text())) is persist


def test_memory_sessions_are_isolated_by_config_path(tmp_path, monkeypatch):
    backend = fail.Keyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    first, second = ConfigStore(tmp_path / "a.json"), ConfigStore(tmp_path / "b.json")
    first.cache_token("a-token", 3600)
    second.cache_token("b-token", 3600)
    assert ConfigStore(first.path).get_cached_token() == "a-token"
    second.clear()
    assert first.get_cached_token() == "a-token"


@pytest.mark.parametrize("backend_type", [fail.Keyring, null.Keyring, chainer.ChainerBackend])
@pytest.mark.parametrize("persist", [False, True])
def test_unusable_backend_does_not_lose_token(tmp_path, monkeypatch, backend_type, persist):
    backend = backend_type()
    if backend_type is chainer.ChainerBackend:
        monkeypatch.setattr(chainer.ChainerBackend, "backends", [])
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    monkeypatch.setattr(keyring, "set_password", backend.set_password)
    monkeypatch.setattr(keyring, "get_password", backend.get_password)
    monkeypatch.setattr(keyring, "delete_password", backend.delete_password)
    ConfigStore._MEM_SECRETS.clear()
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1" if persist else "0")
    store = ConfigStore(tmp_path / "config.json")
    store.cache_token("synthetic-token", 3600)

    assert store.get_cached_token() == "synthetic-token"
    assert ("access_token" in json.loads(store.path.read_text())) is persist


def _store_no_keyring(tmp_path):
    store = ConfigStore(path=tmp_path / "config.json")
    store._use_keyring = False        # force the no-keyring path
    ConfigStore._MEM_SECRETS.clear()  # isolate process-level cache between tests
    return store


def test_token_not_written_to_disk_without_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    store = _store_no_keyring(tmp_path)
    store.cache_token("secret-token", expires_in=3600)

    on_disk = json.loads((tmp_path / "config.json").read_text())
    assert "access_token" not in on_disk          # not persisted
    assert store.get("access_token") == "secret-token"  # but readable in-process


def test_token_written_to_disk_with_env_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store = _store_no_keyring(tmp_path)
    store.cache_token("secret-token", expires_in=3600)

    on_disk = json.loads((tmp_path / "config.json").read_text())
    assert on_disk["access_token"] == "secret-token"


def test_clear_purges_in_memory_token(tmp_path, monkeypatch):
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    store = _store_no_keyring(tmp_path)
    store.cache_token("secret-token", expires_in=3600)
    assert store.get("access_token") == "secret-token"

    store.clear()
    assert store.get("access_token") is None
    assert "access_token" not in ConfigStore._MEM_SECRETS


def test_config_flag_opt_in_persists_token_to_disk(tmp_path, monkeypatch):
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    store = _store_no_keyring(tmp_path)
    # Persist the config-flag opt-in to disk (non-secret key -> save()).
    store.set("allow_insecure_mode", True)
    store.cache_token("secret-token", expires_in=3600)

    on_disk = json.loads((tmp_path / "config.json").read_text())
    assert on_disk["access_token"] == "secret-token"


def test_api_key_is_never_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")  # even with opt-in
    store = _store_no_keyring(tmp_path)
    store.set("api_key", "snp_sk_live_abc")

    cfg = tmp_path / "config.json"
    on_disk = json.loads(cfg.read_text()) if cfg.exists() else {}
    assert "api_key" not in on_disk
    assert "api_key" not in ConfigStore._MEM_SECRETS


def test_atomic_write_failure_preserves_previous_config(tmp_path, monkeypatch):
    store = _store_no_keyring(tmp_path)
    store.set("agent_id", "previous")
    previous = store.path.read_bytes()

    def fail_replace(source, target):
        assert stat.S_IMODE(os.stat(source).st_mode) == 0o600
        raise OSError("synthetic-secret-must-not-be-displayed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(ConfigError) as exc:
        store.set("agent_id", "next")
    assert "synthetic-secret" not in str(exc.value)
    assert store.path.read_bytes() == previous
    assert list(tmp_path.glob("*.tmp")) == []


def test_corrupt_config_is_not_overwritten(tmp_path):
    store = _store_no_keyring(tmp_path)
    store.path.write_text("not json")
    with pytest.raises(ConfigError):
        store.set("agent_id", "next")
    assert store.path.read_text() == "not json"


def test_committed_session_is_origin_bound_and_conditionally_cleared(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store = _store_no_keyring(tmp_path)
    store.commit_session("session-a", 604800, agent_id="agent-a", auth_method="vault",
                         token_origin="https://aipayment.snaplii.com", country="CA")
    assert store.get_cached_token(origin="https://aipayment.snaplii.com") == "session-a"
    assert store.get_cached_token(origin="https://other.example") is None
    store.commit_session("session-b", 3600, agent_id="agent-b", auth_method="api_key",
                         token_origin="https://aipayment.snaplii.com")
    assert store.clear_token(expected_token="session-a") is False
    assert store.get_cached_token() == "session-b"
    assert store.get("country") is None
    assert store.clear_token(expected_token="session-b") is True
    assert store.get_cached_token() is None
    assert store.get("agent_id") == "agent-b"
    assert store.get("auth_method") == "api_key"
    assert "token_expires_at" not in store.load()


def test_safe_status_has_no_secret_prefixes_or_unknown_config(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "0")
    store = _store_no_keyring(tmp_path)
    store.set("unexpected", "synthetic-secret")
    store.commit_session("synthetic-secret-token", 3600, agent_id="agent-a",
                         auth_method="api_key", token_origin="https://aipayment.snaplii.com")
    status = store.auth_status(origin="https://aipayment.snaplii.com")
    assert status["has_valid_token"] is True
    assert status["auth_state"] == "ready"
    assert status["credential_storage"] == "process memory"
    assert status["next_action"] is None
    assert "synthetic-secret" not in json.dumps(status)
    assert "_session" not in json.dumps(status)


def test_keyring_sessions_are_isolated_and_clear_cannot_resurrect(tmp_path, fake_keyring, monkeypatch):
    first, second = ConfigStore(tmp_path / "a.json"), ConfigStore(tmp_path / "b.json")
    first.cache_token("a-token", 3600)
    second.cache_token("b-token", 3600)
    assert first.get_cached_token() == "a-token"
    assert second.get_cached_token() == "b-token"
    assert first.auth_status(origin="https://aipayment.snaplii.com")["credential_storage"] == "system keychain"

    def delete_fails(*args):
        raise RuntimeError("synthetic-secret")

    monkeypatch.setattr(keyring, "delete_password", delete_fails)
    first.clear_token(expected_token="a-token")
    assert ConfigStore(first.path).get_cached_token() is None
    first.clear()
    assert ConfigStore(first.path).get_cached_token() is None
    assert second.get_cached_token() == "b-token"


def test_keyring_and_metadata_mismatch_fails_closed(tmp_path, fake_keyring):
    store = ConfigStore(tmp_path / "config.json")
    store.cache_token("token-a", 3600)
    for name in fake_keyring.values:
        fake_keyring.values[name] = "wrong-generation-token"
    assert store.get_cached_token() is None
    assert store.auth_status(origin="https://aipayment.snaplii.com")["has_valid_token"] is False


@pytest.mark.parametrize("ttl", [3600, 604800])
def test_server_expiry_and_safety_boundary(tmp_path, monkeypatch, ttl):
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store = _store_no_keyring(tmp_path)
    monkeypatch.setattr("time.time", lambda: 1000)
    store.cache_token("token", ttl)
    monkeypatch.setattr("time.time", lambda: 1000 + ttl - 91)
    assert store.get_cached_token() == "token"
    monkeypatch.setattr("time.time", lambda: 1000 + ttl - 90)
    assert store.get_cached_token() is None


def test_stale_save_does_not_replace_new_session(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store = _store_no_keyring(tmp_path)
    store.commit_session("token-a", 3600, agent_id="agent-a", auth_method="vault",
                         token_origin="https://aipayment.snaplii.com")
    stale = store.load()
    store.commit_session("token-b", 3600, agent_id="agent-b", auth_method="vault",
                         token_origin="https://aipayment.snaplii.com")
    stale["_version_check_test"] = 42
    store.save(stale)
    assert store.get_cached_token() == "token-b"
    assert store.get("agent_id") == "agent-b"
    assert store.get("_version_check_test") == 42


def test_symlink_config_is_rejected_without_touching_target(tmp_path):
    target = tmp_path / "target.json"
    target.write_text('{"untouched":true}')
    path = tmp_path / "config.json"
    path.symlink_to(target)
    store = ConfigStore(path)
    with pytest.raises(ConfigError):
        store.set("agent_id", "new-agent")
    assert target.read_text() == '{"untouched":true}'


def test_symlinked_config_directory_is_followed_to_its_target(tmp_path, monkeypatch):
    # stow/chezmoi-managed ~/.snaplii, ostree /home -> /var/home, macOS /var:
    # the directory may be reached through symlinks; only the file may not be one.
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    target = tmp_path / "real"
    target.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    store = ConfigStore(alias / "config.json")
    store._use_keyring = False
    ConfigStore._MEM_SECRETS.clear()
    store.cache_token("synthetic-token", 3600)
    assert ConfigStore(target / "config.json").get_cached_token() == "synthetic-token"
    assert ConfigStore(alias / "config.json").get_cached_token() == "synthetic-token"


def test_group_writable_directory_is_repaired_not_rejected(tmp_path, monkeypatch):
    # An older release created ~/.snaplii under umask 002 (0o775); every command
    # must keep working and the stray write bits are removed.
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    directory = tmp_path / ".snaplii"
    directory.mkdir()
    os.chmod(directory, 0o775)
    store = ConfigStore(directory / "config.json")
    store._use_keyring = False
    ConfigStore._MEM_SECRETS.clear()
    store.cache_token("synthetic-token", 3600)
    assert store.get_cached_token() == "synthetic-token"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755


def test_secret_write_fails_closed_when_file_cannot_be_private(tmp_path, monkeypatch):
    # FAT/exFAT/SMB mounts ignore chmod: never leave a token world-readable.
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store = _store_no_keyring(tmp_path)
    store.set("agent_id", "agent-a")
    monkeypatch.setattr("snaplii._config_file.is_private", lambda path: False)
    with pytest.raises(AuthError) as exc:
        store.commit_session("synthetic-token", 3600, agent_id="agent-a",
                             auth_method="api_key", token_origin=ORIGIN)
    assert exc.value.auth_state == "session_cache_failed"
    assert "private" in exc.value.message
    assert str(store.path) in exc.value.message
    assert "synthetic-token" not in store.path.read_text()


def test_cli_runtime_refuses_memory_only_session(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    ConfigStore._MEM_SECRETS.clear()
    store = ConfigStore(tmp_path / "config.json", runtime="cli")
    with pytest.raises(AuthError) as exc:
        store.commit_session("synthetic-token", 3600, agent_id="agent-1",
                             auth_method="api_key", token_origin=ORIGIN)
    assert exc.value.reason_code == "no_persistent_storage"
    assert "SNAPLII_ALLOW_INSECURE" in exc.value.message
    assert ConfigStore(store.path).get_cached_token() is None
    assert store.get("agent_id") is None


def test_cli_runtime_accepts_file_session_with_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store = ConfigStore(tmp_path / "config.json", runtime="cli")
    store.commit_session("synthetic-token", 3600, agent_id="agent-1",
                         auth_method="api_key", token_origin=ORIGIN)
    assert ConfigStore(store.path).get_cached_token() == "synthetic-token"
    assert store.auth_status(origin=ORIGIN)["credential_storage"] == "config file"


def test_mcp_runtime_memory_recovery_points_to_connect_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    store = ConfigStore(tmp_path / "config.json", runtime="mcp")
    status = store.auth_status(origin=ORIGIN)
    assert status["credential_storage"] == "process memory"
    assert status["next_action"] == {"type": "call_mcp_tool", "tool": "snaplii_connect", "arguments": {}}
    assert ConfigStore(store.path).auth_status(origin=ORIGIN)["next_action"]["type"] == "run_cli"


@pytest.mark.parametrize("state", ["missing", "expired", "rejected"])
@pytest.mark.parametrize("method", ["api_key", "url"])
def test_keychain_mcp_recovery_does_not_require_a_shell(tmp_path, fake_keyring, state, method):
    store = ConfigStore(tmp_path / "config.json", runtime="mcp")
    if state != "missing":
        store.commit_session("synthetic-token", 3600, agent_id="agent-1",
                             auth_method=method, token_origin=ORIGIN)
        if state == "expired":
            store.set("token_expires_at", 1)
        else:
            store.clear_token()
    status = store.auth_status(origin=ORIGIN)
    assert status["has_valid_token"] is False
    assert status["credential_storage"] == "system keychain"
    assert status["next_action"] == {"type": "call_mcp_tool", "tool": "snaplii_connect", "arguments": {}}
    assert ConfigStore(store.path, runtime="cli").auth_status(origin=ORIGIN)["next_action"]["type"] == "run_cli"


def test_keychain_mcp_explicit_secure_auth_keeps_secure_recovery(tmp_path, fake_keyring):
    store = ConfigStore(tmp_path / "config.json", runtime="mcp")
    store.commit_session("synthetic-token", 3600, agent_id="agent-1",
                         auth_method="vault", token_origin=ORIGIN)
    store.set("token_expires_at", 1)
    action = store.auth_status(origin=ORIGIN)["next_action"]
    assert action["type"] == "run_cli"
    assert action["argv"][-1] == "--vault-auth"


@pytest.mark.parametrize("existing_session", [False, True], ids=["first-login", "reauthentication"])
def test_failed_metadata_write_restores_previous_keychain_session(
    tmp_path, fake_keyring, monkeypatch, existing_session
):
    store = ConfigStore(tmp_path / "config.json")
    store.set("base_url", ORIGIN)
    if existing_session:
        store.commit_session("session-a", 3600, agent_id="agent-a", auth_method="api_key", token_origin=ORIGIN)
    previous = store.path.read_bytes()

    def fail_replace(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(AuthError):
        store.commit_session("session-b", 3600, agent_id="agent-b", auth_method="api_key", token_origin=ORIGIN)
    expected = "session-a" if existing_session else None
    assert ConfigStore(store.path).get_cached_token() == expected
    assert fake_keyring.get_password(store._keyring_service, "access_token") == expected
    assert store.path.read_bytes() == previous


@pytest.mark.parametrize("existing_session", [False, True], ids=["first-login", "reauthentication"])
@pytest.mark.parametrize("failure", ["config-read", "metadata-mismatch", "keychain-read"])
def test_post_write_verification_failure_keeps_committed_keychain_session(
    tmp_path, fake_keyring, monkeypatch, existing_session, failure
):
    store = ConfigStore(tmp_path / "config.json")
    if existing_session:
        store.commit_session("session-a", 3600, agent_id="agent-a", auth_method="api_key",
                             token_origin=ORIGIN, country="CA")
    read_config = config_store.read_config
    failure_injected = False

    def flaky_config_read(path):
        nonlocal failure_injected
        data = read_config(path)
        if data.get("agent_id") == "agent-b" and not failure_injected:
            if failure == "config-read":
                failure_injected = True
                raise ConfigError("Cannot read configuration.")
            if failure == "metadata-mismatch":
                failure_injected = True
                return {**data, "agent_id": "inconsistent-readback"}
        return data

    def flaky_keychain_read(service, key):
        nonlocal failure_injected
        # Fail only after the real atomic write. The initial keychain write
        # and its immediate readback still succeed.
        if (failure == "keychain-read" and not failure_injected
                and read_config(store.path).get("agent_id") == "agent-b"):
            failure_injected = True
            raise RuntimeError("Transient keychain read failure")
        return fake_keyring.get_password(service, key)

    monkeypatch.setattr(config_store, "read_config", flaky_config_read)
    monkeypatch.setattr(keyring, "get_password", flaky_keychain_read)
    with pytest.raises(AuthError) as exc:
        store.commit_session("session-b", 3600, agent_id="agent-b", auth_method="api_key",
                             token_origin=ORIGIN, country="US")

    assert failure_injected
    assert exc.value.auth_state == "session_cache_failed"
    assert exc.value.next_action == {"type": "stop", "reason": "session_cache_failed"}
    assert fake_keyring.get_password(store._keyring_service, "access_token") == "session-b"
    persisted = read_config(store.path)
    assert persisted["agent_id"] == "agent-b"
    assert persisted["country"] == "US"
    assert "access_token" not in persisted
    # A new store can reuse the matched session once the transient fault ends.
    recovered = ConfigStore(store.path)
    assert recovered.get_cached_token(origin=ORIGIN) == "session-b"
    assert recovered.auth_status(origin=ORIGIN)["has_valid_token"] is True


@pytest.mark.parametrize("ttl", [3600.0, 604800.0])
def test_whole_number_float_expiry_is_accepted(tmp_path, monkeypatch, ttl):
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store = _store_no_keyring(tmp_path)
    store.commit_session("token", ttl, agent_id="agent-a", auth_method="api_key", token_origin=ORIGIN)
    assert store.get_cached_token() == "token"


def test_cache_failure_reports_its_secret_free_cause(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store = _store_no_keyring(tmp_path)

    def fail_replace(source, target):
        raise OSError("synthetic-secret")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(AuthError) as exc:
        store.commit_session("token", 3600, agent_id="agent-a", auth_method="api_key", token_origin=ORIGIN)
    assert exc.value.auth_state == "session_cache_failed"
    assert "Cannot save configuration securely" in exc.value.message
    assert "synthetic-secret" not in exc.value.message


def test_clear_preserves_empty_lock_file_but_removes_configuration(tmp_path):
    store = _store_no_keyring(tmp_path)
    store.set("agent_id", "agent-a")
    lock = tmp_path / "config.json.lock"
    inode = lock.stat().st_ino
    store.clear()
    assert not store.path.exists()
    assert store.get_cached_token() is None
    assert lock.stat().st_ino == inode
    assert not lock.read_bytes().strip(b"\0")  # Windows may keep one locking byte.


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock regression")
def test_clear_does_not_split_the_lock_between_processes(tmp_path, monkeypatch):
    import fcntl

    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())
    store = ConfigStore(tmp_path / "config.json")
    store.set("agent_id", "agent-a")
    lock = tmp_path / "config.json.lock"
    # Model a writer that opened the lock before clear, but acquires it after.
    descriptor = os.open(lock, os.O_RDWR)
    writer = """
import sys
import keyring
from keyring.backends.fail import Keyring
from pathlib import Path
from snaplii import _config_file
from snaplii.config_store import ConfigStore
from snaplii.exceptions import ConfigError
keyring.get_keyring = lambda: Keyring()
_config_file._LOCK_TIMEOUT = 0.1
try:
    ConfigStore(Path(sys.argv[1])).set('agent_id', 'agent-b')
except ConfigError as exc:
    assert 'busy' in str(exc), str(exc)
    print('blocked')
else:
    print('written')
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "snaplii-cli" / "src")}

    def write_in_other_process():
        result = subprocess.run([sys.executable, "-c", writer, str(store.path)],
                                env=env, text=True, capture_output=True, timeout=5)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    try:
        store.clear()
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert write_in_other_process() == "blocked"
    finally:
        os.close(descriptor)
    assert write_in_other_process() == "written"
    assert store.get("agent_id") == "agent-b"


def test_clear_removes_legacy_keychain_item_after_new_session(tmp_path, fake_keyring):
    fake_keyring.values["snaplii-cli", "access_token"] = "legacy-token"
    store = ConfigStore(tmp_path / "config.json")
    store.commit_session("new-token", 3600, agent_id="agent-a", auth_method="api_key", token_origin=ORIGIN)
    store.clear()
    assert fake_keyring.get_password("snaplii-cli", "access_token") is None


def test_dropping_a_secret_with_none_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store = _store_no_keyring(tmp_path)
    store.cache_token("token", 3600)
    store.set_many({"access_token": None, "agent_id": "agent-a"})
    assert store.get("agent_id") == "agent-a"
    assert store.get_cached_token() == "token"


@pytest.mark.parametrize("operation", ["clear", "clear_token"])
def test_legacy_keyring_session_remains_readable_and_clear_removes_it(tmp_path, fake_keyring, operation):
    store = ConfigStore(tmp_path / "config.json")
    fake_keyring.values["snaplii-cli", "access_token"] = "legacy-token"
    store.set_many({"agent_id": "legacy-agent", "token_expires_at": 9999999999})
    assert store.get_cached_token(origin="https://aipayment.snaplii.com") == "legacy-token"
    getattr(store, operation)()
    assert store.get_cached_token() is None
    assert fake_keyring.get_password("snaplii-cli", "access_token") is None
