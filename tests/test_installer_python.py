import json
import os
import sys

import pytest

from conftest import FakeChild


def probe_json(version, executable="/py", venv_ok=True):
    return json.dumps({"version": list(version), "executable": executable, "venv_ok": venv_ok})


def test_candidate_order_posix_and_windows(installer):
    found = {"python3.12": "/usr/bin/python3.12", "python3.10": "/usr/bin/python3.10", "python3": "/usr/bin/python3",
             "python": "/usr/bin/python", "py": "C:/py.exe"}
    which = lambda name, path=None: found.get(name)
    argvs = installer.candidate_argvs("/opt/mypy", False, {"PATH": "x"}, "linux", "/u/uv", which=which)
    assert argvs[0] == ["/opt/mypy"] and argvs[1] == [sys.executable]
    assert argvs[2:5] == [["/usr/bin/python3.12"], ["/usr/bin/python3.10"], ["/usr/bin/python3"]]
    assert ["/usr/bin/python"] in argvs
    assert ["/u/uv", "python", "find", "--no-project", "3.14"] in argvs
    assert ["/u/uv", "python", "find", "--no-project", "3.9"] not in argvs
    assert not any(a[:2] == ["C:/py.exe", "-3.12"] for a in argvs)
    win = installer.candidate_argvs(None, True, {"PATH": "x"}, "win32", None, which=which)
    assert ["C:/py.exe", "-3.12"] in win and ["C:/py.exe", "-3.9"] in win
    assert win.index(["C:/py.exe", "-3.14"]) > win.index(["/usr/bin/python"])


def test_probe_resolves_uv_find_then_runs_probe_code(installer, fake_run):
    rules = fake_run["rules"]
    rules.append((lambda a: a[1:3] == ["python", "find"], FakeChild(installer, 0, "/managed/python3.12\n")))
    rules.append((lambda a: a[0] == "/managed/python3.12", FakeChild(installer, 0, probe_json((3, 12, 1), "/managed/python3.12"))))
    info = installer.probe(["/u/uv", "python", "find", "--no-project", "3.12"], {})
    assert info["argv"] == ["/managed/python3.12"] and info["version"] == [3, 12, 1]
    assert fake_run["calls"][1]["argv"][-2:] == ["-c", installer.PROBE_CODE]


def test_qualifying_candidates_skip_old_missing_ensurepip_and_duplicates(installer, fake_run):
    rules = fake_run["rules"]
    rules.append((lambda a: a[0] == "/old", FakeChild(installer, 0, probe_json((3, 9, 2), "/old"))))
    rules.append((lambda a: a[0] == "/noensure", FakeChild(installer, 0, probe_json((3, 12, 0), "/noensure", venv_ok=False))))
    rules.append((lambda a: a[0] in ("/good", "/good-alias"), FakeChild(installer, 0, probe_json((3, 11, 4), "/good"))))
    rules.append((lambda a: a[0] == "/broken", FakeChild(installer, 1, "", "boom")))
    warnings = []
    out = installer.qualifying_candidates([["/old"], ["/noensure"], ["/good"], ["/good-alias"], ["/broken"]],
                                          (3, 10), {}, "/old", warnings)
    assert [c["executable"] for c in out] == ["/good"]
    assert any("--python" in w for w in warnings)


def test_locate_uv_order(installer, tmp_path):
    env = {"HOME": str(tmp_path), "PATH": "", "UV_INSTALL_DIR": str(tmp_path / "custom"),
           "XDG_BIN_HOME": str(tmp_path / "xdgbin"), "XDG_DATA_HOME": str(tmp_path / "xdgdata")}
    present = set()
    exists = lambda p: p in present
    which = lambda name, path=None: None
    assert installer.locate_uv(env, which=which, exists=exists) is None
    present.add(str(tmp_path / ".local" / "bin" / "uv"))
    assert installer.locate_uv(env, which=which, exists=exists) == str(tmp_path / ".local" / "bin" / "uv")
    present.add(os.path.normpath(str(tmp_path / "xdgdata" / ".." / "bin" / "uv")))
    assert installer.locate_uv(env, which=which, exists=exists).endswith(os.path.join("bin", "uv"))
    present.add(str(tmp_path / "xdgbin" / "uv"))
    assert installer.locate_uv(env, which=which, exists=exists) == str(tmp_path / "xdgbin" / "uv")
    present.add(str(tmp_path / "custom" / "uv"))
    assert installer.locate_uv(env, which=which, exists=exists) == str(tmp_path / "custom" / "uv")
    assert installer.locate_uv(env, which=lambda n, path=None: "/on/path/uv", exists=exists) == "/on/path/uv"


def test_install_uv_sets_install_dir_and_no_modify_path(installer, fake_run, tmp_path, monkeypatch):
    target = tmp_path / ".local" / "bin"
    target.mkdir(parents=True)

    def installed(argv):
        (target / "uv").write_text("")
        return FakeChild(installer, 0)
    fake_run["rules"].append((lambda a: a[0] == "sh", installed))
    environ = {"HOME": str(tmp_path), "PATH": "/usr/bin"}
    which = lambda name, path=None: "/usr/bin/curl" if name == "curl" else None
    path = installer.install_uv(environ, installer.child_env(environ, for_uv=True), which=which)
    assert path == str(target / "uv")
    call = fake_run["calls"][0]
    assert call["argv"][:2] == ["sh", "-c"] and "curl -LsSf https://astral.sh/uv/install.sh | sh" in call["argv"][2]
    assert call["env"]["UV_INSTALL_DIR"] == str(target) and call["env"]["UV_NO_MODIFY_PATH"] == "1"


def test_install_uv_without_a_fetcher_is_python_too_old(installer, fake_run, tmp_path):
    with pytest.raises(installer.InstallFailure) as info:
        installer.install_uv({"HOME": str(tmp_path), "PATH": ""}, {}, which=lambda n, path=None: None)
    assert info.value.code == "python_too_old" and info.value.retryable is True


def test_acquire_python_sequence_and_env_scrub(installer, fake_run, tmp_path, clean_env, monkeypatch):
    monkeypatch.setenv("UV_NO_MANAGED_PYTHON", "1")
    monkeypatch.setenv("UV_PYTHON_INSTALL_MIRROR", "https://mirror")
    environ = dict(os.environ, HOME=str(tmp_path))
    rules = fake_run["rules"]
    rules.append((lambda a: a[1:3] == ["python", "install"], FakeChild(installer, 0)))
    rules.append((lambda a: a[1:3] == ["python", "find"], FakeChild(installer, 0, "/managed/3.12/python\n")))
    rules.append((lambda a: a[0] == "/managed/3.12/python", FakeChild(installer, 0, probe_json((3, 12, 11), "/managed/3.12/python"))))
    monkeypatch.setattr(installer, "locate_uv", lambda environ, **kw: "/u/uv")
    info = installer.acquire_python(environ, installer.child_env(environ, for_uv=True), (3, 10))
    assert info["acquired_by"] == "uv" and info["version"] == [3, 12, 11]
    calls = fake_run["calls"]
    assert calls[0]["argv"] == ["/u/uv", "python", "install", "--no-bin", "--no-registry", "3.12"]
    assert calls[1]["argv"] == ["/u/uv", "python", "find", "--no-project", "--managed-python", "3.12"]
    assert "UV_NO_MANAGED_PYTHON" not in calls[0]["env"] and calls[0]["env"]["UV_PYTHON_INSTALL_MIRROR"] == "https://mirror"


def test_acquire_python_download_failure(installer, fake_run, tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "locate_uv", lambda environ, **kw: "/u/uv")
    fake_run["rules"].append((lambda a: a[1:3] == ["python", "install"], FakeChild(installer, 1, "", "error: network unreachable")))
    with pytest.raises(installer.InstallFailure) as info:
        installer.acquire_python({"HOME": str(tmp_path)}, {}, (3, 10))
    assert info.value.code == "python_download_failed" and info.value.retryable is True
    assert "network unreachable" in info.value.diagnostics


def test_symlinked_duplicate_is_probed_once(installer, fake_run, tmp_path):
    real = tmp_path / "python3.12"
    real.write_text("")
    alias = tmp_path / "python3"
    alias.symlink_to(real)
    fake_run["rules"].append((lambda a: a[0] in (str(real), str(alias)),
                              FakeChild(installer, 0, probe_json((3, 12, 4), str(real)))))
    out = installer.qualifying_candidates([[str(real)], [str(alias)]], (3, 10), {}, None, [])
    assert [c["executable"] for c in out] == [str(real)]
    assert len(fake_run["calls"]) == 1
