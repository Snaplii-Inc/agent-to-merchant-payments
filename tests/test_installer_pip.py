import os
import sys

import pytest

from conftest import FakeChild


@pytest.mark.parametrize("output, code, retryable", [
    ("ERROR: HTTP error 401 while getting https://mirror/simple/", "index_auth_failed", False),
    ("User for mirror.example: ", "index_auth_failed", False),
    ("SSLError(SSLCertVerificationError CERTIFICATE_VERIFY_FAILED)", "tls_failed", False),
    ("WARNING: Retrying ... NewConnectionError ... Max retries exceeded\nERROR: No matching distribution found for snaplii-mcp", "index_unreachable", True),
    ("ERROR: Could not find a version that satisfies the requirement snaplii-mcp", "package_unavailable", False),
    ("ERROR: Failed building wheel for pydantic-core", "build_failed", False),
    ("OSError: [Errno 28] No space left on device", "disk_full", True),
    ("PermissionError: [WinError 32] The process cannot access the file because it is being used by another process", "files_in_use", True),
    ("Access is denied: 'C:\\\\env\\\\Scripts\\\\snaplii-mcp.exe'", "permission_denied", False),
    ("PermissionError: [Errno 13] Permission denied", "permission_denied", False),
    ("something else entirely", "pip_failed", False),
    ("Downloading pydantic_core.whl (401 kB)\nOSError: [Errno 28] No space left on device", "disk_full", True),
    ("403 Client Error: Forbidden for url: https://mirror/simple/snaplii-cli/", "index_auth_failed", False),
])
def test_classify_pip_precedence(installer, output, code, retryable):
    assert installer.classify_pip(output) == (code, retryable)


def test_package_specs(installer):
    assert installer.package_specs(False, None) == ["snaplii-cli", "snaplii-mcp"]
    assert installer.package_specs(True, None) == ["snaplii-cli"]
    assert installer.package_specs(False, "/src") == [os.path.join("/src", "snaplii-cli"), os.path.join("/src", "mcp-server")]
    assert installer.package_specs(True, "/src") == [os.path.join("/src", "snaplii-cli")]


def test_pip_floor_upgrades_old_pip_only(installer, fake_run):
    rules = fake_run["rules"]
    rules.append((lambda a: a[-1] == "--version", FakeChild(installer, 0, "pip 21.2.3 from /x (python 3.10)")))
    rules.append((lambda a: "pip>=23.1" in a, FakeChild(installer, 0)))
    assert installer.pip_floor_ok("/py", {}) is False
    installer.ensure_pip_floor("/py", {})
    assert any("pip>=23.1" in c["argv"] for c in fake_run["calls"])
    fake_run["calls"].clear()
    rules.insert(0, (lambda a: a[-1] == "--version", FakeChild(installer, 0, "pip 23.1 from /x (python 3.10)")))
    installer.ensure_pip_floor("/py", {})
    assert not any("pip>=23.1" in c["argv"] for c in fake_run["calls"])


def test_pip_install_argv_and_single_retry(installer, fake_run, monkeypatch):
    monkeypatch.setattr(installer.time, "sleep", lambda s: None)
    attempts = []

    def flaky(argv):
        attempts.append(argv)
        if len(attempts) == 1:
            return FakeChild(installer, 1, "", "ERROR: Could not fetch URL https://pypi.org/simple/: connection error")
        return FakeChild(installer, 0)
    fake_run["rules"].append((lambda a: "install" in a, flaky))
    installer.pip_install("/py", ["snaplii-cli", "snaplii-mcp"], {})
    assert len(attempts) == 2
    assert attempts[0][:4] == ["/py", "-m", "pip", "install"]
    for flag in ("--upgrade", "--prefer-binary", "--no-input", "--keyring-provider", "disabled", "--timeout", "30", "--retries", "2"):
        assert flag in attempts[0]
    assert attempts[0][-2:] == ["snaplii-cli", "snaplii-mcp"]


def test_pip_install_non_retryable_failure_is_not_retried(installer, fake_run, monkeypatch):
    monkeypatch.setattr(installer.time, "sleep", lambda s: None)
    fake_run["rules"].append((lambda a: "install" in a, FakeChild(installer, 1, "", "ERROR: No matching distribution found for snaplii-mcp")))
    with pytest.raises(installer.InstallFailure) as info:
        installer.pip_install("/py", ["snaplii-cli", "snaplii-mcp"], {})
    assert info.value.code == "package_unavailable" and len(fake_run["calls"]) == 1
    assert "No matching distribution" in info.value.diagnostics


def test_install_packages_runs_floor_install_and_check(installer, fake_run):
    rules = fake_run["rules"]
    rules.append((lambda a: a[-1] == "--version", FakeChild(installer, 0, "pip 24.0 from /x (python 3.12)")))
    rules.append((lambda a: "install" in a, FakeChild(installer, 0)))
    rules.append((lambda a: a[-1] == "check", FakeChild(installer, 1, "snaplii-mcp 0.19.0 requires snaplii-cli>=0.19.0")))
    with pytest.raises(installer.InstallFailure) as info:
        installer.install_packages("/py", False, None, {"PIP_CONFIG_FILE": os.devnull})
    assert info.value.code == "dependency_conflict"
    argvs = [c["argv"] for c in fake_run["calls"]]
    assert argvs[0][-1] == "--version" and "install" in argvs[1] and argvs[2][-1] == "check"
    assert not any("config" in a for a in argvs)


def test_files_in_use_remedy_names_the_host(installer):
    assert "close the host" in installer.pip_remedy("files_in_use")
    assert "PIP_INDEX_URL" in installer.pip_remedy("index_unreachable")


def test_pip_conf_is_never_opened_and_pip_children_get_the_scrubbed_env(installer, fake_run, tmp_path, monkeypatch):
    for rel in (".config/pip/pip.conf", ".pip/pip.conf"):
        conf = tmp_path / rel
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text("[install]\ntarget = /elsewhere\n")
    opened = []
    real_open = open

    def spy(path, *args, **kwargs):
        opened.append(str(path))
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(installer, "open", spy, raising=False)
    rules = fake_run["rules"]
    rules.append((lambda a: a[-1] == "--version", FakeChild(installer, 0, "pip 24.0 from /x (python 3.12)")))
    rules.append((lambda a: "install" in a or a[-1] == "check", FakeChild(installer, 0)))
    environ = {"HOME": str(tmp_path), "PATH": "/usr/bin", "PIP_TARGET": "/elsewhere", "PIP_INDEX_URL": "https://m/simple",
               "PYTHONPATH": "/x"}
    installer.install_packages("/py", False, None, installer.child_env(environ))
    assert not any("pip.conf" in path for path in opened)
    for call in fake_run["calls"]:
        assert call["env"]["PIP_CONFIG_FILE"] == os.devnull and "PIP_TARGET" not in call["env"]
        assert "PYTHONPATH" not in call["env"] and call["env"]["PIP_INDEX_URL"] == "https://m/simple"
