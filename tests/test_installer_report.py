import json
import os
import sys

import pytest


def installed(installer, exe_dir="/home/u/.snaplii-env/bin"):
    return {"cli": {"status": "installed", "version": "0.19.0", "executable": exe_dir + "/snaplii", "host_seen_by_cli": "unknown"},
            "mcp": {"status": "installed", "version": "0.19.0", "executable": exe_dir + "/snaplii-mcp", "tools": 26}}


def ids(steps):
    return [s["id"] for s in steps]


def test_render_command_posix_and_powershell(installer):
    assert installer.render_command("claude", ["mcp", "add", "snaplii", "--", "/a b/snaplii-mcp"], "linux") == "claude mcp add snaplii -- '/a b/snaplii-mcp'"
    rendered = installer.render_command("C:\\Users\\O'Brien\\my env\\Scripts\\snaplii-mcp.exe", ["$x"], "win32")
    assert rendered.startswith("& '") and "''Brien" in rendered and "'$x'" in rendered


def test_next_steps_per_host(installer):
    comps = installed(installer)
    for host, exe, first in [("claude-code", "claude", "claude mcp add snaplii -- /home/u/.snaplii-env/bin/snaplii-mcp"),
                             ("codex", "codex", "codex mcp add snaplii -- /home/u/.snaplii-env/bin/snaplii-mcp"),
                             ("openclaw", "openclaw", "openclaw mcp add snaplii --command /home/u/.snaplii-env/bin/snaplii-mcp")]:
        steps = installer.next_steps(host, "unknown", comps, "/home/u/.snaplii-env", None, False, False, "linux", {"HOME": "/home/u"}, ["python3", "install.py"])
        assert ids(steps) == ["install_skill", "register_mcp", "reload_host", "connect", "cli_on_path", "update"]
        register = steps[1]
        assert register["executable"] == exe and register["command"] == first and register["status"] == "pending"
    skill = installer.next_steps("claude-code", "unknown", comps, "/v", None, False, False, "linux", {}, [])[0]
    assert skill["args"] == ["skills", "add", "Snaplii-Inc/agent-to-merchant-payments", "-a", "claude-code"]
    assert installer.next_steps("openclaw", "unknown", comps, "/v", None, False, False, "linux", {}, [])[0]["command"] == "clawhub install snaplii-a2m-payment"
    desktop = installer.next_steps("claude-desktop", "unknown", comps, "/v", None, False, False, "darwin", {"HOME": "/Users/u"}, [])[1]
    assert desktop["file"].endswith("Library/Application Support/Claude/claude_desktop_config.json")
    assert desktop["json"] == {"mcpServers": {"snaplii": {"command": "/home/u/.snaplii-env/bin/snaplii-mcp"}}}
    cursor = installer.next_steps("cursor", "unknown", comps, "/v", None, False, False, "linux", {}, [])[1]
    assert cursor["file"] == ".cursor/mcp.json" and cursor["json"]["mcpServers"]["snaplii"]["command"].endswith("snaplii-mcp")
    instinct = installer.next_steps("codex", "instinct", comps, "/v", None, False, False, "linux", {}, [])
    assert "install_skill" not in ids(instinct) and "snaplii_connect" in instinct[0]["why"] and instinct[0]["id"] == "register_mcp"
    generic = installer.next_steps(None, "unknown", comps, "/v", None, False, False, "linux", {}, [])[1]
    assert generic["executable"].endswith("snaplii-mcp") and "README" in generic["why"]


def test_next_steps_gating(installer):
    comps = installed(installer)
    comps["mcp"] = {"status": "failed"}
    retryable = installer.InstallFailure("verify", "mcp_handshake_failed", "x", "re-run", retryable=True)
    steps = installer.next_steps("claude-code", "unknown", comps, "/v", retryable, False, False, "linux", {}, ["python3", "install.py", "--host", "claude-code"])
    assert "register_mcp" not in ids(steps) and "update" not in ids(steps)
    required = [s for s in steps if s["status"] == "required"][0]
    assert required["command"] == "python3 install.py --host claude-code" and "re-run" in required["why"]
    fatal = installer.InstallFailure("pip", "index_auth_failed", "x", "fix the index", retryable=False)
    steps = installer.next_steps("claude-code", "unknown", comps, "/v", fatal, False, False, "linux", {}, [])
    required = [s for s in steps if s["status"] == "required"][0]
    assert required["id"] == "report_to_user" and required["command"] is None and "fix the index" in required["why"]
    comps["mcp"] = {"status": "skipped"}
    steps = installer.next_steps("instinct", "unknown", comps, "/v", None, False, True, "linux", {}, ["python3", "install.py", "--cli-only"])
    required = [s for s in steps if s["status"] == "required"][0]
    assert "--cli-only" in required["why"] and "--cli-only" not in required["command"]
    comps = {"cli": {"status": "missing"}, "mcp": {"status": "missing"}}
    steps = installer.next_steps("claude-code", "unknown", comps, "/v", None, True, False, "linux", {}, ["python3", "install.py", "--check"])
    required = [s for s in steps if s["status"] == "required"][0]
    assert required["command"] == "python3 install.py" and "cli_on_path" not in ids(steps)


def test_compute_status(installer):
    comps = installed(installer)
    assert installer.compute_status(comps, None, False, False) == "installed"
    comps["mcp"] = {"status": "failed"}
    assert installer.compute_status(comps, None, False, False) == "partial"
    assert installer.compute_status({"cli": {"status": "installed"}, "mcp": {"status": "skipped"}}, None, False, True) == "installed"
    assert installer.compute_status({"cli": {"status": "not_verified"}, "mcp": {"status": "not_verified"}}, "f", False, False) == "failed"
    assert installer.compute_status({"cli": {"status": "missing"}, "mcp": {"status": "missing"}}, None, True, False) == "not_installed"


def run_main(installer, capsys, argv, environ):
    code = installer.main(argv, environ)
    out = capsys.readouterr()
    return code, json.loads(out.out)


def test_main_bad_arguments_and_help(installer, capsys, tmp_path):
    code, report = run_main(installer, capsys, ["--host", "Claude-Code"], {"HOME": str(tmp_path)})
    assert code == 1 and report["status"] == "failed" and report["failure"]["code"] == "bad_arguments"
    assert report["host"]["detected"] == "unknown"  # the host object is present on every report
    assert installer.main(["--help"], {"HOME": str(tmp_path)}) == 0


def test_main_instinct_refuses_cli_only_before_any_subprocess(installer, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no subprocess expected")))
    code, report = run_main(installer, capsys, ["--cli-only"], {"HOME": str(tmp_path), "INSTINCT_X": "1"})
    assert code == 1 and report["failure"]["code"] == "mcp_required_on_instinct" and report["failure"]["retryable"] is False
    assert report["host"]["detected"] == "instinct" and report["host"]["instinct_variables"] == ["INSTINCT_X"]


def test_main_source_invalid_and_host_precedence_warnings(installer, capsys, tmp_path):
    src = tmp_path / "src"
    (src / "snaplii-cli").mkdir(parents=True)
    code, report = run_main(installer, capsys, ["--source", str(src)], {"HOME": str(tmp_path)})
    assert report["failure"]["code"] == "source_invalid" and "mcp-server" in report["failure"]["remedy"]
    assert not (tmp_path / ".snaplii-env.lock").exists()
    code, report = run_main(installer, capsys, ["--check", "--host", "codex"], {"HOME": str(tmp_path), "INSTINCT_Y": ""})
    assert any("--host" in w and "Instinct" in w for w in report["warnings"])
    code, report = run_main(installer, capsys, ["--check", "--host", "instinct"], {"HOME": str(tmp_path)})
    assert any("instinct" in w.lower() for w in report["warnings"]) and report["status"] == "not_installed"


def test_main_check_mode_absent_and_reserved_states(installer, capsys, tmp_path):
    code, report = run_main(installer, capsys, ["--check"], {"HOME": str(tmp_path)})
    assert code == 1 and report["status"] == "not_installed" and report["venv"]["state"] == "absent"
    assert report["components"] == {"cli": {"status": "missing"}, "mcp": {"status": "missing"}}
    assert not (tmp_path / ".snaplii-env.creating").exists() and not (tmp_path / ".snaplii-env.lock").exists()


def test_main_install_happy_path_with_fake_stages(installer, capsys, tmp_path, monkeypatch):
    venv = str(tmp_path / ".snaplii-env")
    monkeypatch.setattr(installer, "locate_uv", lambda environ, **k: None)
    monkeypatch.setattr(installer, "qualifying_candidates", lambda *a, **k: [{"argv": [sys.executable], "executable": sys.executable, "version": [3, 12, 0], "venv_ok": True}])

    def fake_build(venv_path, reservation, candidates, need, env, mode):
        os.makedirs(venv_path, exist_ok=True)
        installer.write_marker(venv_path, sys.executable)
        reservation.remove()
        return {"executable": installer.venv_python(venv_path), "version": [3, 12, 0], "state": "created"}
    monkeypatch.setattr(installer, "build_venv", fake_build)
    monkeypatch.setattr(installer, "install_packages", lambda *a, **k: None)
    monkeypatch.setattr(installer, "verify_cli", lambda v, env, t: {"status": "installed", "version": "0.19.0", "executable": installer.venv_exe(v, "snaplii"), "host_seen_by_cli": "unknown"})
    monkeypatch.setattr(installer, "verify_mcp", lambda v, env, t, w: {"status": "installed", "version": "0.19.0", "executable": installer.venv_exe(v, "snaplii-mcp"), "tools": 26})
    code, report = run_main(installer, capsys, ["--host", "claude-code"], {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", "")})
    assert code == 0 and report["status"] == "installed" and report["venv"] == {"path": venv, "state": "created"}
    assert report["python"]["acquired_by"] is None and report["installer_version"] == "1"
    assert ids(report["next_steps"]) == ["install_skill", "register_mcp", "reload_host", "connect", "cli_on_path", "update"]
    assert "close the host" in [s for s in report["next_steps"] if s["id"] == "update"][0]["why"]
    assert not os.path.exists(venv + ".lock")
    monkeypatch.setattr(installer, "validate_existing", lambda v, need, env: {"executable": installer.venv_python(v), "version": [3, 12, 0]})
    code, report = run_main(installer, capsys, ["--check", "--host", "claude-code"], {"HOME": str(tmp_path)})
    assert code == 0 and report["status"] == "installed" and report["venv"]["state"] == "reused"
    assert "update" in ids(report["next_steps"])


def test_main_partial_and_pip_failure_states(installer, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "qualifying_candidates", lambda *a, **k: [{"argv": [sys.executable], "executable": sys.executable, "version": [3, 12, 0], "venv_ok": True}])

    def fake_build(venv_path, reservation, candidates, need, env, mode):
        os.makedirs(venv_path, exist_ok=True)
        installer.write_marker(venv_path, sys.executable)
        reservation.remove()
        return {"executable": installer.venv_python(venv_path), "version": [3, 12, 0], "state": "created"}
    monkeypatch.setattr(installer, "build_venv", fake_build)
    monkeypatch.setattr(installer, "install_packages", lambda *a, **k: None)
    monkeypatch.setattr(installer, "verify_cli", lambda v, env, t: {"status": "installed", "version": "0.19.0", "executable": "x", "host_seen_by_cli": "unknown"})

    def bad_mcp(v, env, t, w):
        raise installer.InstallFailure("verify", "mcp_handshake_failed", "boom", "re-run", retryable=True)
    monkeypatch.setattr(installer, "verify_mcp", bad_mcp)
    code, report = run_main(installer, capsys, [], {"HOME": str(tmp_path)})
    assert code == 1 and report["status"] == "partial" and report["components"]["mcp"]["status"] == "failed"
    assert report["failure"]["code"] == "mcp_handshake_failed"

    def bad_pip(*a, **k):
        raise installer.InstallFailure("pip", "index_unreachable", "down", "retry", retryable=True)
    monkeypatch.setattr(installer, "install_packages", bad_pip)
    code, report = run_main(installer, capsys, ["--venv", str(tmp_path / "other")], {"HOME": str(tmp_path)})
    assert report["status"] == "failed" and report["venv"]["state"] == "partial_install"
    assert report["components"] == {"cli": {"status": "not_verified"}, "mcp": {"status": "not_verified"}}


def test_main_python_download_failure_leaves_state_absent(installer, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "qualifying_candidates", lambda *a, **k: [])

    def no_python(*a, **k):
        raise installer.InstallFailure("python", "python_download_failed", "offline", installer.required_python_remedy(), retryable=True)
    monkeypatch.setattr(installer, "acquire_python", no_python)
    code, report = run_main(installer, capsys, [], {"HOME": str(tmp_path)})
    assert report["status"] == "failed" and report["venv"]["state"] == "absent"
    assert [s for s in report["next_steps"] if s["status"] == "required"]


def test_main_cleanup_incomplete_retains_the_lock(installer, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "qualifying_candidates", lambda *a, **k: [])

    def leaves_survivors(*a, **k):
        installer.SURVIVORS.append(4242)
        raise installer.InstallFailure("python", "python_download_failed", "x", "y", retryable=True)
    monkeypatch.setattr(installer, "acquire_python", leaves_survivors)
    monkeypatch.setattr(installer, "SURVIVORS", [])
    code, report = run_main(installer, capsys, [], {"HOME": str(tmp_path)})
    assert report["failure"]["code"] == "cleanup_incomplete" and report["failure"]["retryable"] is False
    lock = json.load(open(str(tmp_path / ".snaplii-env.lock")))
    assert lock["state"] == "cleanup_incomplete" and lock["surviving_pids"] == [4242]


def test_main_check_mode_builds_a_bytecode_free_child_environment(installer, capsys, tmp_path, monkeypatch):
    seen = []
    real = installer.child_env

    def spy(base, check_mode=False, for_uv=False):
        env = real(base, check_mode=check_mode, for_uv=for_uv)
        seen.append(env.get("PYTHONDONTWRITEBYTECODE"))
        return env
    monkeypatch.setattr(installer, "child_env", spy)
    run_main(installer, capsys, ["--check"], {"HOME": str(tmp_path)})
    assert seen == ["1"]
    seen.clear()
    monkeypatch.setattr(installer, "qualifying_candidates", lambda *a, **k: [])
    monkeypatch.setattr(installer, "acquire_python", lambda *a, **k: (_ for _ in ()).throw(
        installer.InstallFailure("python", "python_download_failed", "x", "y", retryable=True)))
    run_main(installer, capsys, [], {"HOME": str(tmp_path)})
    assert "1" not in seen                     # install mode never sets it


def test_next_steps_cli_failure_with_mcp_installed_still_has_a_required_step(installer):
    comps = installed(installer)
    comps["cli"] = {"status": "failed", "code": "cli_verification_failed"}
    failure = installer.InstallFailure("verify", "cli_verification_failed", "doctor crashed", "re-run", retryable=True)
    steps = installer.next_steps("claude-code", "unknown", comps, "/v", failure, False, False, "linux", {}, ["python3", "install.py"])
    assert "register_mcp" in ids(steps) and "cli_on_path" not in ids(steps) and "update" not in ids(steps)
    assert [s["id"] for s in steps if s["status"] == "required"] == ["retry"]
