import json
import sys

import keyring
import pytest
from keyring.backends.fail import Keyring

from snaplii import auth, cli
from snaplii.config_store import ConfigStore


def trace(version, **extra):
    return json.dumps({"app_version": version, **extra})


@pytest.mark.parametrize("version, outdated", [
    ("9.0.0.23.177", True),
    ("8.9.9.99.999", True),
    ("9.0.0.23", True),
    ("9.0.0.23.178", False),
    ("9.0.0.23.178.0", False),
    ("9.0.0.24.0", False),
    ("10.0.0.0.0", False),
])
def test_muse_app_version_threshold(monkeypatch, version, outdated):
    monkeypatch.setenv("JARVIS_TRACE_CONTEXT", trace(version))
    assert auth.muse_app_outdated() is outdated


@pytest.mark.parametrize("context", [
    None, "", "not json", "[]", "{}", '{"app_version": null}', '{"app_version": "not-a-version"}',
    "[" * 200_000 + "]" * 200_000,  # RecursionError, not ValueError
])
def test_unknown_muse_app_version_is_not_reported(monkeypatch, context):
    if context is None:
        monkeypatch.delenv("JARVIS_TRACE_CONTEXT", raising=False)
    else:
        monkeypatch.setenv("JARVIS_TRACE_CONTEXT", context)
    assert auth.muse_app_outdated() is False


@pytest.mark.parametrize("version, in_muse, notice", [
    ("9.0.0.23.100", True, True),
    ("9.0.0.23.178", True, False),
    ("9.0.0.23.100", False, False),
])
def test_config_show_reports_outdated_muse_app_without_leaking_trace(
    muse_filesystem, tmp_path, monkeypatch, capsys, version, in_muse, notice,
):
    if not in_muse:
        muse_filesystem[str(auth.MUSE_SOCKET)] = None
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.setattr(cli, "ConfigStore", lambda: ConfigStore(tmp_path / "config.json"))
    monkeypatch.setattr(cli, "check_for_update", lambda *a: None)
    # The trace context also carries conversation text; only app_version may be read.
    monkeypatch.setenv("JARVIS_TRACE_CONTEXT", trace(version, recent_conversation="private-chat-text"))
    monkeypatch.setattr(sys, "argv", ["snaplii", "config", "show"])
    cli._cli()
    output = capsys.readouterr()
    assert output.err == ""
    assert "private-chat-text" not in output.out
    # Users are told to update without version numbers, theirs or the minimum.
    assert version not in output.out
    assert auth.MUSE_MIN_APP_VERSION not in output.out
    state = json.loads(output.out)
    assert state["host"] == ("muse" if in_muse else "unknown")
    if notice:
        assert "once per conversation" in state["muse_app_update"]
        assert "version numbers" in state["muse_app_update"]
    else:
        assert "muse_app_update" not in state
