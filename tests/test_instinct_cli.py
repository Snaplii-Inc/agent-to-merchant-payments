import json
import shlex
import sys

import click
import keyring
import pytest
from keyring.backends.fail import Keyring

from snaplii import auth, cli

LOCAL = ("config", "help", "update")


def _leaves(command, prefix=()):
    if isinstance(command, click.Group):
        return {path for name, child in command.commands.items()
                for path in _leaves(child, prefix + (name,))}
    return {" ".join(prefix)}


BLOCKED = sorted(path for path in _leaves(cli.main) if path.split()[0] not in LOCAL)


@pytest.fixture
def instinct_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.setenv("SNAPLII_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.delenv("SNAPLII_BASE_URL", raising=False)
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    monkeypatch.setattr(cli, "check_for_update", lambda *args, **kwargs: None)
    return tmp_path / "config.json"


def _run(monkeypatch, capsys, command):
    monkeypatch.setattr(sys, "argv", ["snaplii", *shlex.split(command)])
    try:
        cli._cli()
        code = 0
    except SystemExit as exc:
        code = exc.code
    return code, capsys.readouterr()


def test_blocked_list_covers_init_and_business_commands():
    assert "init" in BLOCKED and "balance" in BLOCKED and "transfer create" in BLOCKED


@pytest.mark.parametrize("command", BLOCKED)
def test_cli_refuses_init_and_business_commands(instinct_cli, monkeypatch, capsys, httpx_mock, command):
    code, output = _run(monkeypatch, capsys, command)
    assert code == 1
    assert output.out == ""
    result = json.loads(output.err)
    assert result["auth_state"] == "mcp_required"
    assert result["reason_code"] == "instinct_requires_mcp"
    assert result["next_action"] == auth.build_auth_action("mcp_required", host="instinct")
    assert "INSTINCT_AGENT_ID" in result["message"]
    assert "synthetic-value" not in output.err
    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize("command", ["help", "--version", "update", "config show", "config doctor", "config clear"])
def test_cli_keeps_local_commands(instinct_cli, monkeypatch, capsys, httpx_mock, command):
    code, output = _run(monkeypatch, capsys, command)
    assert code == 0
    assert output.err == ""
    assert output.out
    assert httpx_mock.get_requests() == []


def test_show_and_doctor_name_variables_without_values(instinct_cli, monkeypatch, capsys):
    _, output = _run(monkeypatch, capsys, "config show")
    shown = json.loads(output.out)
    assert shown["host"] == "instinct"
    assert shown["instinct_env"] == ["INSTINCT_AGENT_ID"]
    _, output = _run(monkeypatch, capsys, "config doctor")
    doctor = json.loads(output.out)
    assert doctor["instinct"] == {"detected": True, "reason_code": "instinct_env_present",
                                  "env_names": ["INSTINCT_AGENT_ID"]}
    assert doctor["authentication"]["host"] == "instinct"
    assert "synthetic-value" not in output.out


def test_corrupt_config_still_points_to_mcp_and_doctor_reports_instinct(
    instinct_cli, monkeypatch, capsys,
):
    instinct_cli.write_text("{not json")
    code, output = _run(monkeypatch, capsys, "balance")
    assert code == 1
    assert json.loads(output.err)["auth_state"] == "mcp_required"
    code, output = _run(monkeypatch, capsys, "config doctor")
    assert code == 0
    authentication = json.loads(output.out)["authentication"]
    assert authentication["auth_state"] == "session_cache_failed"
    assert authentication["host"] == "instinct"
