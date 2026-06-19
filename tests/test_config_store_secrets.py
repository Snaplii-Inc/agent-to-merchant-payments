import json

from snaplii.config_store import ConfigStore


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
