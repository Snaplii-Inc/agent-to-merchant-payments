import json
import os
import sys
from pathlib import Path

import pytest

FAKE = str(Path(__file__).resolve().parent / "helpers" / "fake_mcp_server.py")
INSTALLED_MCP = Path(sys.executable).parent / ("snaplii-mcp.exe" if os.name == "nt" else "snaplii-mcp")


def fake_argv():
    return [sys.executable, FAKE]


def env_for(installer, clean_env, **extra):
    env = installer.child_env(dict(os.environ))
    env.update(extra)
    return env


def test_valid_protocol_date(installer):
    assert installer.valid_protocol_date("2025-06-18") and installer.valid_protocol_date("2024-11-05")
    assert installer.valid_protocol_date("2026-01-01")
    for bad in ("2024-06-01", "latest", 20250618, "2025-13-01", None):
        assert not installer.valid_protocol_date(bad)


def test_handshake_normal_and_instinct_counts_against_fake(installer, clean_env, tmp_path):
    warnings = []
    assert installer.mcp_handshake(fake_argv(), env_for(installer, clean_env), str(tmp_path), warnings) == 26
    assert warnings == []
    assert not (tmp_path / "config.json").exists()
    assert installer.mcp_handshake(fake_argv(), env_for(installer, clean_env, FAKE_MCP_TOOLS="24"), str(tmp_path), []) == 24


@pytest.mark.parametrize("mode", ["bad_json", "wrong_id", "paginate", "empty_cursor"])
def test_handshake_tolerates_noise_and_pagination(installer, clean_env, tmp_path, mode):
    assert installer.mcp_handshake(fake_argv(), env_for(installer, clean_env, FAKE_MCP_MODE=mode), str(tmp_path), []) == 26


@pytest.mark.parametrize("mode, detail", [
    ("hang", "timeout"), ("flood", "flood"), ("eof", "eof"), ("oversize", "oversize"), ("error", "error"),
    ("no_tools_cap", "tools capability"), ("paginate_forever", "terminate"), ("creates_config", "configuration file"),
    ("close_stdin", "transport"),
])
def test_handshake_failures(installer, clean_env, tmp_path, mode, detail, monkeypatch):
    monkeypatch.setitem(installer.DEADLINES, "mcp", 3)
    with pytest.raises(installer.InstallFailure) as info:
        installer.mcp_handshake(fake_argv(), env_for(installer, clean_env, FAKE_MCP_MODE=mode), str(tmp_path), [])
    assert info.value.code in ("mcp_handshake_failed", "mcp_timeout")
    assert detail in (info.value.message + info.value.code)
    assert "SENTINEL9" not in json.dumps(info.value.to_dict())


def test_handshake_protocol_date_rule(installer, clean_env, tmp_path):
    with pytest.raises(installer.InstallFailure) as info:
        installer.mcp_handshake(fake_argv(), env_for(installer, clean_env, FAKE_MCP_PROTOCOL="2024-06-01"), str(tmp_path), [])
    assert "protocolVersion" in info.value.message
    with pytest.raises(installer.InstallFailure):
        installer.mcp_handshake(fake_argv(), env_for(installer, clean_env, FAKE_MCP_PROTOCOL="latest"), str(tmp_path), [])
    warnings = []
    assert installer.mcp_handshake(fake_argv(), env_for(installer, clean_env, FAKE_MCP_PROTOCOL="2026-01-01"), str(tmp_path), warnings) == 26
    assert warnings and "2026-01-01" in warnings[0]


def test_handshake_sends_a_complete_initialize_and_initialized(installer, clean_env, tmp_path, fake_child):
    recorder = fake_child("""
        import json, sys
        log = open(%r, 'a')
        for line in sys.stdin:
            log.write(line); log.flush()
            msg = json.loads(line)
            if msg.get('method') == 'initialize':
                print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}}})); sys.stdout.flush()
            elif msg.get('method') == 'tools/list':
                print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'tools': [{'name': 'snaplii_config_show'}]}})); sys.stdout.flush()
    """ % str(tmp_path / "log.jsonl"))
    assert installer.mcp_handshake(recorder, env_for(installer, clean_env), str(tmp_path), []) == 1
    sent = [json.loads(l) for l in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert sent[0]["method"] == "initialize" and sent[0]["params"]["protocolVersion"] == "2025-06-18"
    assert sent[0]["params"]["clientInfo"] == {"name": "snaplii-install", "version": "1"}
    assert sent[1] == {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert sent[2]["method"] == "tools/list" and sent[2]["id"] == 2


@pytest.mark.skipif(not INSTALLED_MCP.exists(), reason="snaplii-mcp is not installed next to the test interpreter")
def test_real_server_handshake_normal_and_instinct(installer, clean_env, tmp_path):
    env = env_for(installer, clean_env)
    assert installer.mcp_handshake([str(INSTALLED_MCP)], env, str(tmp_path), []) == 26
    assert installer.mcp_handshake([str(INSTALLED_MCP)], dict(env, INSTINCT_TEST="1"), str(tmp_path), []) == 24
    assert not (tmp_path / "config.json").exists()


def test_verify_cli_against_the_test_environment(installer, clean_env, tmp_path):
    result = installer.verify_cli(sys.prefix, env_for(installer, clean_env), str(tmp_path))
    assert result["status"] == "installed" and result["version"]
    assert result["executable"].endswith("snaplii" + (".exe" if os.name == "nt" else ""))
    assert result["host_seen_by_cli"] in ("unknown", "muse", "instinct")
    assert not (tmp_path / "doctor-config.json").exists()


def test_verify_cli_failures(installer, clean_env, tmp_path, monkeypatch):
    with pytest.raises(installer.InstallFailure) as info:
        installer.verify_cli(str(tmp_path / "nope"), {}, str(tmp_path))
    assert info.value.code == "cli_missing"
    monkeypatch.setattr(installer, "metadata_version", lambda python, dist, env: "0.0.0")
    with pytest.raises(installer.InstallFailure) as info:
        installer.verify_cli(sys.prefix, env_for(installer, clean_env), str(tmp_path))
    assert info.value.code == "cli_verification_failed" and "metadata" in info.value.message


def test_verify_mcp_missing_and_real(installer, clean_env, tmp_path):
    with pytest.raises(installer.InstallFailure) as info:
        installer.verify_mcp(str(tmp_path / "nope"), {}, str(tmp_path), [])
    assert info.value.code == "mcp_missing"
    if INSTALLED_MCP.exists():
        result = installer.verify_mcp(sys.prefix, env_for(installer, clean_env), str(tmp_path), [])
        assert result["status"] == "installed" and result["tools"] == 26 and result["version"]
