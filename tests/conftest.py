import sys
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# snaplii package (editable install also works, but be explicit for CI)
sys.path.insert(0, str(ROOT / "snaplii-cli" / "src"))
# mcp-server/server.py is a standalone module, not a package
sys.path.insert(0, str(ROOT / "mcp-server"))


@pytest.fixture
def muse_filesystem(monkeypatch):
    """Synthetic OS metadata at the host boundary; no host detector override."""
    helper = Path("/opt/hatch/skills/skill-creator/bin/dynamic_credentials.py")
    socket = Path("/run/hatch/auth/authd.sock")
    metadata = {str(path): (stat.S_IFDIR | 0o755, 0)
                for target in (helper, socket) for path in target.parents}
    metadata[str(helper)] = (stat.S_IFREG | 0o644, 0)
    metadata[str(socket)] = (stat.S_IFSOCK | 0o660, 0)
    def synthetic_stat(original):
        def probe(path, *args, **kwargs):
            if str(path) not in metadata:
                return original(path, *args, **kwargs)
            value = metadata[str(path)]
            if value is None:
                raise FileNotFoundError
            if isinstance(value, OSError):
                raise value
            mode, owner = value
            return os.stat_result((mode, 1, 1, 1, owner, 0, 0, 0, 0, 0))
        return probe

    monkeypatch.setattr(os, "stat", synthetic_stat(os.stat))
    monkeypatch.setattr(os, "lstat", synthetic_stat(os.lstat))
    monkeypatch.setattr(sys, "platform", "linux")
    return metadata


@pytest.fixture(autouse=True)
def _no_instinct_environment(monkeypatch):
    """A stray INSTINCT_ variable on a developer machine or CI must not flip tests
    into Instinct mode; Instinct tests set their own variables."""
    for name in list(os.environ):
        if name.startswith("INSTINCT_"):
            monkeypatch.delenv(name)


import importlib.util
import textwrap


@pytest.fixture
def installer():
    """Load scripts/install.py as a module without importing anything from src/."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "install.py"
    spec = importlib.util.spec_from_file_location("snaplii_install", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clean_env(monkeypatch):
    """Strip host-detection, uv, pip and Python variables so tests see a neutral environment."""
    for name in list(os.environ):
        if name.startswith(("INSTINCT_", "UV_", "PIP_", "PYTHON", "SNAPLII_")):
            monkeypatch.delenv(name, raising=False)
    return dict(os.environ)


@pytest.fixture
def fake_child(tmp_path):
    """Write a small Python child script and return its argv."""
    def make(body, name="child.py"):
        script = tmp_path / name
        script.write_text(textwrap.dedent(body))
        return [sys.executable, str(script)]
    return make


class FakeChild:
    """A finished child for tests: returncode plus redacted stdout/stderr buffers."""

    def __init__(self, installer, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout, self.stderr = installer.LineBuffer(), installer.LineBuffer()
        for line in out.splitlines():
            self.stdout.add_text(line)
        for line in err.splitlines():
            self.stderr.add_text(line)


@pytest.fixture
def fake_run(installer, monkeypatch):
    """Route installer.run through a table of (predicate, result) rules; record every call."""
    calls = []
    rules = []

    def run(argv, stage, deadline, env, cwd=None):
        calls.append({"argv": list(argv), "stage": stage, "env": dict(env), "cwd": cwd})
        for predicate, result in rules:
            if predicate(argv):
                return result(argv) if callable(result) else result
        raise AssertionError("unexpected child: %r" % (argv,))

    monkeypatch.setattr(installer, "run", run)
    return {"calls": calls, "rules": rules}
