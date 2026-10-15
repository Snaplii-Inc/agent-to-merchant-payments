"""Where a terminal login keeps its session, and which gateway later commands use.

Without a keychain, `init` asks before the key is typed whether sessions may be
kept in the owner-only config file, so the user never types a key for a login
that cannot be kept. A gateway chosen for the login becomes the saved default.
"""

import io
import json
import sys

import click
import keyring
import pytest
from keyring.backends.fail import Keyring

import server
from snaplii import cli
from snaplii.config_store import ConfigStore
from snaplii.exceptions import ConfigError

PROD = "https://aipayment.snaplii.com"
STAGING = "https://aipay.stage.snaplii.com"
KEY = "snp_sk_live_syntheticapikey00000000000000000"


class MemoryKeyring:
    priority = 1

    def __init__(self, fail_writes=False):
        self.values = {}
        self.fail_writes = fail_writes

    def get_password(self, service, key):
        return self.values.get((service, key))

    def set_password(self, service, key, value):
        if self.fail_writes:
            raise RuntimeError("synthetic-keyring-failure")
        self.values[service, key] = value

    def delete_password(self, service, key):
        self.values.pop((service, key), None)


@pytest.fixture
def path(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    for name in ("SNAPLII_ALLOW_INSECURE", "SNAPLII_BASE_URL", "SNAPLII_ELICIT_URL"):
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / "config.json"
    monkeypatch.setenv("SNAPLII_CONFIG_PATH", str(config))
    # A fresh store per command, as in separate processes.
    monkeypatch.setattr(cli, "ConfigStore", lambda: ConfigStore(config))
    monkeypatch.setattr(cli, "check_for_update", lambda store: None)
    return config


@pytest.fixture
def terminal(monkeypatch):
    """A person at a terminal: records the questions and answers them."""
    seen = {"confirm": [], "prompt": []}

    def answer_confirm(yes):
        def confirm(text, **kwargs):
            seen["confirm"].append(text)
            assert kwargs.get("default") is False and kwargs.get("err") is True
            if isinstance(yes, BaseException):
                raise yes
            return yes
        monkeypatch.setattr("snaplii.commands.init.click.confirm", confirm)

    def prompt(text, **kwargs):
        seen["prompt"].append(text)
        assert kwargs.get("hide_input") is True
        return KEY

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("snaplii.commands.init.click.prompt", prompt)
    seen["answer"] = answer_confirm
    answer_confirm(True)
    return seen


def run(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["snaplii", *args])
    cli._cli()
    output = capsys.readouterr()
    return json.loads(output.out)


def run_error(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["snaplii", *args])
    with pytest.raises(SystemExit) as exc:
        cli._cli()
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    return json.loads(output.err)


def token_response(httpx_mock, base_url=PROD):
    httpx_mock.add_response(method="POST", url=base_url + "/v2/auth/token",
                            json={"access_token": "synthetic-token", "expires_in": 600})


# ── no keychain: ask before the key ───────────────────────────────────────────

def test_yes_keeps_this_and_later_sessions_in_the_file(path, terminal, monkeypatch, capsys, httpx_mock):
    token_response(httpx_mock)
    state = run(monkeypatch, capsys, "init")
    assert state["has_valid_token"] is True
    assert state["credential_storage"] == "config file"
    question = terminal["confirm"][0]
    assert str(path) in question and "future" in question and "never saved" in question
    assert len(terminal["prompt"]) == 1
    assert json.loads(path.read_text())["allow_insecure_mode"] is True
    # The next process reuses the session without any opt-in in its environment.
    assert run(monkeypatch, capsys, "config", "show")["has_valid_token"] is True


def test_no_stops_before_the_key_is_typed(path, terminal, monkeypatch, capsys, httpx_mock):
    terminal["answer"](False)
    err = run_error(monkeypatch, capsys, "init")
    assert err["auth_state"] == "session_cache_failed"
    assert err["reason_code"] == "no_persistent_storage"
    assert terminal["prompt"] == []
    assert not path.exists() or "allow_insecure_mode" not in json.loads(path.read_text())


@pytest.mark.parametrize("interrupt", [click.Abort(), EOFError()])
def test_interrupting_the_question_cancels(path, terminal, monkeypatch, capsys, httpx_mock, interrupt):
    terminal["answer"](interrupt)
    err = run_error(monkeypatch, capsys, "init")
    assert err["reason_code"] == "cancelled"
    assert terminal["prompt"] == []


@pytest.mark.parametrize("opt_in", ["env", "config"])
def test_an_existing_opt_in_is_not_asked_again(path, terminal, monkeypatch, capsys, httpx_mock, opt_in):
    if opt_in == "env":
        monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    else:
        path.write_text(json.dumps({"allow_insecure_mode": True}))
    token_response(httpx_mock)
    assert run(monkeypatch, capsys, "init")["has_valid_token"] is True
    assert terminal["confirm"] == []


def test_a_working_keychain_is_not_asked_about(path, terminal, monkeypatch, capsys, httpx_mock):
    backend = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    for name in ("set_password", "get_password", "delete_password"):
        monkeypatch.setattr(keyring, name, getattr(backend, name))
    token_response(httpx_mock)
    state = run(monkeypatch, capsys, "init")
    assert state["credential_storage"] == "system keychain"
    assert terminal["confirm"] == []


def test_a_failed_preference_write_stops_before_the_key(path, terminal, monkeypatch, capsys, httpx_mock):
    def refuse(self, key, value):
        raise ConfigError("Could not write the configuration file.")
    monkeypatch.setattr(ConfigStore, "set", refuse)
    err = run_error(monkeypatch, capsys, "init")
    assert "configuration file" in err["message"]
    assert terminal["prompt"] == []


def test_a_keychain_that_fails_on_write_still_reports_it(path, terminal, monkeypatch, capsys, httpx_mock):
    # The backend looks usable, so nothing is asked; the failure shows when saving.
    backend = MemoryKeyring(fail_writes=True)
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    for name in ("set_password", "get_password", "delete_password"):
        monkeypatch.setattr(keyring, name, getattr(backend, name))
    token_response(httpx_mock)
    err = run_error(monkeypatch, capsys, "init")
    assert err["reason_code"] == "no_persistent_storage"
    assert terminal["confirm"] == []
    assert "synthetic" not in json.dumps(err)


def test_piped_input_is_never_asked(path, monkeypatch, capsys, httpx_mock):
    monkeypatch.setattr(sys, "stdin", io.StringIO(KEY + "\n"))
    monkeypatch.setattr("snaplii.commands.init.click.confirm",
                        lambda *a, **k: pytest.fail("no question without a terminal"))
    token_response(httpx_mock)
    err = run_error(monkeypatch, capsys, "init")
    assert err["reason_code"] == "no_persistent_storage"


# ── the gateway signed in to becomes the default ─────────────────────────────

@pytest.fixture
def file_storage(path, monkeypatch):
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    monkeypatch.setattr(sys, "stdin", io.StringIO(KEY + "\n"))
    return path


@pytest.mark.parametrize("base_url", [STAGING, STAGING + "/payments"])
def test_a_chosen_gateway_is_used_by_later_commands(file_storage, monkeypatch, capsys, httpx_mock, base_url):
    token_response(httpx_mock, base_url)
    assert run(monkeypatch, capsys, "--base-url", base_url + "/", "init")["has_valid_token"] is True
    assert json.loads(file_storage.read_text())["base_url"] == base_url
    state = run(monkeypatch, capsys, "config", "show")
    assert state["has_valid_token"] is True and state["base_url"] == base_url
    httpx_mock.add_response(method="GET", url=base_url + "/v2/balance", json={"balance": 42})
    assert run(monkeypatch, capsys, "balance")["balance"] == 42


def test_a_gateway_from_the_environment_is_kept_after_it_is_unset(file_storage, monkeypatch, capsys, httpx_mock):
    monkeypatch.setenv("SNAPLII_BASE_URL", STAGING)
    token_response(httpx_mock, STAGING)
    run(monkeypatch, capsys, "init")
    monkeypatch.delenv("SNAPLII_BASE_URL")
    assert run(monkeypatch, capsys, "config", "show")["base_url"] == STAGING


def test_the_environment_still_overrides_the_saved_gateway(file_storage, monkeypatch, capsys, httpx_mock):
    token_response(httpx_mock, STAGING)
    run(monkeypatch, capsys, "--base-url", STAGING, "init")
    monkeypatch.setenv("SNAPLII_BASE_URL", PROD)
    state = run(monkeypatch, capsys, "config", "show")
    assert state["base_url"] == PROD and state["has_valid_token"] is False


def test_a_failed_login_keeps_the_saved_gateway(file_storage, monkeypatch, capsys, httpx_mock):
    file_storage.write_text(json.dumps({"base_url": PROD}))
    httpx_mock.add_response(method="POST", url=STAGING + "/v2/auth/token", status_code=401,
                            json={"message": "Snaplii core rejected the credentials"})
    run_error(monkeypatch, capsys, "--base-url", STAGING, "init")
    assert json.loads(file_storage.read_text())["base_url"] == PROD


def test_a_login_without_a_chosen_gateway_writes_none(file_storage, monkeypatch, capsys, httpx_mock):
    token_response(httpx_mock)
    run(monkeypatch, capsys, "init")
    assert "base_url" not in json.loads(file_storage.read_text())


def test_the_mcp_server_follows_the_saved_gateway(file_storage, monkeypatch, capsys, httpx_mock):
    token_response(httpx_mock, STAGING)
    run(monkeypatch, capsys, "--base-url", STAGING, "init")
    assert server._base_url() == STAGING
