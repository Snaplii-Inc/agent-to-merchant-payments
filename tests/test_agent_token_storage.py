"""Where the phone connection's tokens are kept: where the API-key session's would be, never in plain sight."""
import hashlib
import json
import stat

import pytest

from snaplii import auth
from snaplii.config_store import AGENT_TOKEN, CONNECT_TOKEN, ConfigStore
from snaplii.exceptions import AuthError

TOKEN = "snp_ag_longterm0000000000000000000000000000000000"
ORIGIN = "https://aipayment.snaplii.com"


def keychain_service(store):
    return "snaplii-cli:" + hashlib.sha256(str(store.path.resolve()).encode()).hexdigest()


def connect(store, token=TOKEN):
    store.update_agent_connection(tokens={AGENT_TOKEN: token}, fields={"agent_name": "muse", "agent_origin": ORIGIN})


def test_with_a_keychain_the_token_goes_there_and_config_json_only_has_its_digest(tmp_path, memory_keyring):
    store = ConfigStore(tmp_path / "config.json")

    connect(store)

    assert memory_keyring.values[keychain_service(store), AGENT_TOKEN] == TOKEN
    on_disk = json.loads(store.path.read_text())
    assert TOKEN not in store.path.read_text()
    assert on_disk["agent_name"] == "muse" and on_disk["agent_origin"] == ORIGIN
    assert on_disk["_agent_credential_storage"] == "system keychain"
    assert ConfigStore(store.path).get_agent_secret(AGENT_TOKEN) == TOKEN


def test_on_muse_the_token_goes_to_the_owner_only_config_file(tmp_path, monkeypatch, memory_keyring):
    monkeypatch.setattr(auth, "detect_muse", lambda: auth.MuseEnvironment(True, "test_only"))
    store = ConfigStore(tmp_path / "config.json")

    connect(store)

    assert json.loads(store.path.read_text())[AGENT_TOKEN] == TOKEN
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert memory_keyring.values == {}
    assert ConfigStore(store.path).get_agent_secret(AGENT_TOKEN) == TOKEN


def test_with_the_insecure_opt_in_and_no_keychain_the_token_goes_to_the_owner_only_file(tmp_path, monkeypatch):
    import keyring
    from keyring.backends.fail import Keyring
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store = ConfigStore(tmp_path / "config.json")

    connect(store)

    assert json.loads(store.path.read_text())[AGENT_TOKEN] == TOKEN
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_with_nowhere_to_keep_it_the_token_is_refused_not_held_in_memory(tmp_path, monkeypatch):
    import keyring
    from keyring.backends.fail import Keyring
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    store = ConfigStore(tmp_path / "config.json")

    with pytest.raises(AuthError) as refused:
        store.agent_token_storage()
    assert refused.value.reason_code == "no_persistent_storage"
    with pytest.raises(AuthError):
        connect(store)
    assert store.get_agent_secret(AGENT_TOKEN) is None


def test_a_later_plain_setting_keeps_a_file_that_holds_the_token_owner_only(tmp_path, monkeypatch, memory_keyring):
    monkeypatch.setattr(auth, "detect_muse", lambda: auth.MuseEnvironment(True, "test_only"))
    store = ConfigStore(tmp_path / "config.json")
    connect(store)
    store.path.chmod(0o600)

    store.set("country", "CA")

    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert store.get_agent_secret(AGENT_TOKEN) == TOKEN


def test_a_keychain_item_without_its_digest_in_config_json_is_never_used(tmp_path, memory_keyring):
    store = ConfigStore(tmp_path / "config.json")
    memory_keyring.values[keychain_service(store), AGENT_TOKEN] = "snp_ag_left_behind"

    assert store.get_agent_secret(AGENT_TOKEN) is None


def test_config_clear_removes_the_tokens_from_the_keychain(tmp_path, memory_keyring):
    store = ConfigStore(tmp_path / "config.json")
    connect(store)
    store.update_agent_connection(tokens={CONNECT_TOKEN: "snp_ct_waiting"})

    store.clear()

    assert memory_keyring.values == {}
    assert store.get_agent_secret(AGENT_TOKEN) is None


def test_ending_the_api_key_session_leaves_the_phone_connection(tmp_path, memory_keyring):
    store = ConfigStore(tmp_path / "config.json")
    store.commit_session("api-key-session-token", 3600, agent_id="agent-1", auth_method="api_key",
                         token_origin=ORIGIN)
    connect(store)

    store.clear_token()

    assert store.get_cached_token(origin=ORIGIN) is None
    assert store.get_agent_secret(AGENT_TOKEN) == TOKEN


def test_a_new_api_key_session_leaves_the_phone_connection(tmp_path, memory_keyring):
    store = ConfigStore(tmp_path / "config.json")
    connect(store)

    store.commit_session("api-key-session-token", 3600, agent_id="agent-1", auth_method="api_key",
                         token_origin=ORIGIN)

    assert store.get_cached_token(origin=ORIGIN) == "api-key-session-token"
    assert store.get_agent_secret(AGENT_TOKEN) == TOKEN


def test_removing_the_token_removes_its_keychain_item(tmp_path, memory_keyring):
    store = ConfigStore(tmp_path / "config.json")
    connect(store)

    store.update_agent_connection(remove=(AGENT_TOKEN, "agent_name", "agent_origin"))

    assert memory_keyring.values == {}
    on_disk = json.loads(store.path.read_text())
    assert not {"agent_name", "agent_origin", "_agent_secret_digests", "_agent_credential_storage"} & on_disk.keys()
