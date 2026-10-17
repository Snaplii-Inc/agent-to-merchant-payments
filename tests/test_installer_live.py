"""Real-interpreter and live tests: Python 3.8 compatibility and full installs (network-gated)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install.py"
LIVE = os.environ.get("SNAPLII_INSTALLER_LIVE") == "1"


def find_python38():
    uv = shutil.which("uv")
    if not uv:
        return None
    found = subprocess.run([uv, "python", "find", "--no-project", "--managed-python", "3.8"],
                           capture_output=True, text=True)
    path = found.stdout.strip().splitlines()[-1] if found.returncode == 0 and found.stdout.strip() else None
    return path if path and os.path.exists(path) else None


PY38 = find_python38()


@pytest.mark.skipif(PY38 is None, reason="CPython 3.8 not installed (CI installs it with `uv python install 3.8`)")
def test_script_runs_under_real_python_3_8(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("INSTINCT_", "PYTHON"))}
    env["HOME"] = str(tmp_path)
    helped = subprocess.run([PY38, str(SCRIPT), "--help"], capture_output=True, text=True, env=env)
    assert helped.returncode == 0 and "--check" in helped.stdout
    checked = subprocess.run([PY38, str(SCRIPT), "--check", "--venv", str(tmp_path / "absent")],
                             capture_output=True, text=True, env=env)
    assert checked.returncode == 1
    report = json.loads(checked.stdout)
    assert report["status"] == "not_installed" and report["venv"]["state"] == "absent"


def run_installer(args, home):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("INSTINCT_", "PYTHON"))}
    env["HOME"] = str(home)
    completed = subprocess.run([sys.executable, str(SCRIPT)] + args, capture_output=True, text=True, env=env, timeout=1200)
    return completed.returncode, json.loads(completed.stdout), completed.stderr


@pytest.mark.skipif(not LIVE, reason="set SNAPLII_INSTALLER_LIVE=1 to run the network installs")
def test_live_source_install(tmp_path):
    code, report, stderr = run_installer(["--source", str(ROOT), "--venv", str(tmp_path / "env"), "--host", "claude-code"], tmp_path)
    assert code == 0, stderr
    assert report["status"] == "installed" and report["venv"]["state"] == "created"
    assert report["components"]["mcp"]["tools"] in (24, 26)
    assert [s["id"] for s in report["next_steps"]][:2] == ["install_skill", "register_mcp"]


@pytest.mark.skipif(not LIVE, reason="set SNAPLII_INSTALLER_LIVE=1 to run the network installs")
def test_live_default_pypi_install_and_rerun(tmp_path):
    code, first, stderr = run_installer(["--venv", str(tmp_path / "env")], tmp_path)
    assert code == 0, stderr
    assert first["status"] == "installed" and first["venv"]["state"] == "created"
    code, second, stderr = run_installer(["--venv", str(tmp_path / "env")], tmp_path)
    assert code == 0, stderr
    assert second["venv"]["state"] == "reused"
    assert second["components"]["cli"]["version"] == first["components"]["cli"]["version"]
    assert second["components"]["mcp"]["version"] == first["components"]["mcp"]["version"]
    assert any(s["id"] == "update" for s in second["next_steps"])
