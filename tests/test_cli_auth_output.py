import json
import io
import sys

import keyring
import pytest
from keyring.backends.fail import Keyring

from snaplii import cli
from snaplii.config_store import ConfigStore


@pytest.mark.parametrize("command", [["config", "show"], ["init", "--vault-auth"]])
def test_auth_json_is_not_prefixed_by_update_notice(tmp_path, monkeypatch, capsys, command):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    store = ConfigStore(tmp_path / "config.json")
    monkeypatch.setattr(cli, "ConfigStore", lambda: store)
    monkeypatch.setattr(cli, "check_for_update", lambda *a: {"current": "0.16.0", "latest": "99.0.0"})
    monkeypatch.setenv("SNAPLII_VAULT_HELPER_PATH", str(tmp_path / "missing"))
    monkeypatch.setattr(sys, "argv", ["snaplii", *command])
    if command[0] == "init":
        with pytest.raises(SystemExit) as exc:
            cli._cli()
        assert exc.value.code == 1
        output = capsys.readouterr()
        assert output.out == ""
        assert json.loads(output.err)["auth_state"] == "secure_entry_unavailable"
    else:
        cli._cli()
        output = capsys.readouterr()
        assert output.err == ""
        assert json.loads(output.out)["has_valid_token"] is False


def test_noninteractive_raw_login_emits_only_safe_json(tmp_path, monkeypatch, capsys, httpx_mock):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store = ConfigStore(tmp_path / "config.json")
    monkeypatch.setattr(cli, "ConfigStore", lambda: store)
    monkeypatch.setattr(sys, "argv", ["snaplii", "init"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("synthetic-api-key\n"))
    httpx_mock.add_response(method="POST", json={"access_token": "synthetic-token", "debug": "synthetic-secret"})
    cli._cli()
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["has_valid_token"] is True
    assert "synthetic" not in output.out


def test_empty_stdin_is_structured_error_not_a_second_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.setattr(cli, "ConfigStore", lambda: ConfigStore(tmp_path / "config.json"))
    monkeypatch.setattr(sys, "argv", ["snaplii", "init"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(SystemExit) as exc:
        cli._cli()
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["reason_code"] == "api_key_missing"


def test_cli_login_without_persistent_storage_fails_visibly(tmp_path, monkeypatch, capsys, httpx_mock):
    # A one-shot CLI process must not report a session that dies with it.
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    monkeypatch.setattr(cli, "ConfigStore", lambda: ConfigStore(tmp_path / "config.json"))
    monkeypatch.setattr(sys, "argv", ["snaplii", "init"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("synthetic-api-key\n"))
    httpx_mock.add_response(method="POST", json={"access_token": "synthetic-token", "expires_in": 600})
    with pytest.raises(SystemExit) as exc:
        cli._cli()
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    err = json.loads(output.err)
    assert err["auth_state"] == "session_cache_failed"
    assert err["reason_code"] == "no_persistent_storage"
    assert "synthetic" not in output.err


def test_invalid_agent_id_is_rejected_before_any_network_exchange(tmp_path, monkeypatch, capsys, httpx_mock):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    monkeypatch.setattr(cli, "ConfigStore", lambda: ConfigStore(tmp_path / "config.json"))
    monkeypatch.setattr(sys, "argv", ["snaplii", "init", "--agent-id", "my agent"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("synthetic-api-key\n"))
    with pytest.raises(SystemExit) as exc:
        cli._cli()
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().err)["message"] == "Invalid agent ID."
    assert httpx_mock.get_requests() == []


def test_config_clear_repairs_corrupt_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    path = tmp_path / "config.json"
    path.write_text("not json")
    monkeypatch.setattr(cli, "ConfigStore", lambda: ConfigStore(path))
    monkeypatch.setattr(sys, "argv", ["snaplii", "config", "clear"])
    cli._cli()
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    assert not path.exists()


def test_config_set_replaces_invalid_stored_gateway(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.delenv("SNAPLII_BASE_URL", raising=False)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"base_url": "localhost:8080"}))
    monkeypatch.setattr(cli, "ConfigStore", lambda: ConfigStore(path))
    monkeypatch.setattr(sys, "argv", ["snaplii", "config", "set", "--base-url", "https://gateway.example"])
    cli._cli()
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    assert json.loads(path.read_text())["base_url"] == "https://gateway.example"


def test_path_prefixed_gateway_survives_config_login_and_recovery(tmp_path, monkeypatch, capsys, httpx_mock):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    monkeypatch.delenv("SNAPLII_BASE_URL", raising=False)
    store = ConfigStore(tmp_path / "config.json")
    monkeypatch.setattr(cli, "ConfigStore", lambda: store)
    base_url = "https://aipay.stage.snaplii.com/payments"

    def run(*args):
        monkeypatch.setattr(sys, "argv", ["snaplii", *args])
        cli._cli()
        output = capsys.readouterr()
        assert output.err == ""
        return json.loads(output.out)

    assert run("config", "set", "--base-url", base_url + "/")["status"] == "ok"
    assert store.get("base_url") == base_url
    state = run("config", "show")
    assert state["base_url"] == base_url
    assert state["next_action"]["argv"] == ["snaplii", "--base-url", base_url, "init"]

    monkeypatch.setattr(sys, "stdin", io.StringIO("synthetic-api-key\n"))
    httpx_mock.add_response(method="POST", url=base_url + "/v2/auth/token",
                            json={"access_token": "synthetic-token", "expires_in": 600})
    assert run("init")["has_valid_token"] is True
    assert store.get("token_origin") == "https://aipay.stage.snaplii.com"
    httpx_mock.add_response(method="GET", url=base_url + "/v2/balance", json={"balance": 42})
    assert run("balance")["balance"] == 42

    httpx_mock.add_response(method="GET", url=base_url + "/v2/balance", status_code=401, json={})
    monkeypatch.setattr(sys, "argv", ["snaplii", "balance"])
    with pytest.raises(SystemExit):
        cli._cli()
    rejected = json.loads(capsys.readouterr().err)
    assert rejected["next_action"]["argv"] == ["snaplii", "--base-url", base_url, "init"]
