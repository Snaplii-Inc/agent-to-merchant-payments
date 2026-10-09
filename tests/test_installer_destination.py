import os
from pathlib import Path

import pytest


def test_config_dir_defaults_to_home_snaplii_and_honours_config_path(installer, tmp_path):
    assert installer.config_dir({"HOME": str(tmp_path)}) == str(tmp_path / ".snaplii")
    cfg = tmp_path / "cfg" / "config.json"
    assert installer.config_dir({"SNAPLII_CONFIG_PATH": str(cfg)}) == str(tmp_path / "cfg")


def test_resolve_destination_defaults_and_resolves_symlinked_parents(installer, tmp_path):
    env = {"HOME": str(tmp_path)}
    assert installer.resolve_destination(None, env) == str(tmp_path / ".snaplii-env")
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert installer.resolve_destination(str(link / "env"), env) == str(real / "env")


@pytest.mark.parametrize("make", ["config_dir", "inside_config_dir", "config_inside_venv"])
def test_resolve_destination_refuses_the_configuration_directory_both_ways(installer, tmp_path, make):
    env = {"HOME": str(tmp_path)}
    if make == "config_dir":
        target = tmp_path / ".snaplii"
    elif make == "inside_config_dir":
        target = tmp_path / ".snaplii" / "env"
    else:
        env["SNAPLII_CONFIG_PATH"] = str(tmp_path / "env" / "cfg" / "config.json")
        target = tmp_path / "env"
    with pytest.raises(installer.InstallFailure) as info:
        installer.resolve_destination(str(target), env)
    assert info.value.code == "venv_path_occupied" and info.value.retryable is False


def test_resolve_destination_refuses_symlink_and_non_directory(installer, tmp_path):
    env = {"HOME": str(tmp_path)}
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "venv-link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(installer.InstallFailure) as info:
        installer.resolve_destination(str(link), env)
    assert info.value.code == "venv_path_occupied"
    plain = tmp_path / "file"
    plain.write_text("x")
    with pytest.raises(installer.InstallFailure) as info:
        installer.resolve_destination(str(plain), env)
    assert info.value.code == "venv_path_occupied"


import json
import subprocess
import sys


def test_lock_acquire_release_and_ordinary_remedy(installer, tmp_path):
    venv = str(tmp_path / "env")
    lock = installer.Lock(venv)
    lock.acquire()
    assert json.loads(open(lock.path).read())["pid"] == os.getpid()
    other = installer.Lock(venv)
    with pytest.raises(installer.InstallFailure) as info:
        other.acquire()
    assert info.value.code == "venv_locked" and info.value.retryable is True
    assert "delete" in info.value.remedy and "no installer is running" in info.value.remedy
    lock.release()
    assert not os.path.exists(lock.path)


def test_lock_retained_after_incomplete_cleanup_guides_by_liveness(installer, tmp_path):
    venv = str(tmp_path / "env")
    lock = installer.Lock(venv)
    lock.acquire()
    lock.retain([os.getpid()])
    lock.release()                                   # retained locks survive release
    record = json.loads(open(lock.path).read())
    assert record["state"] == "cleanup_incomplete" and record["surviving_pids"] == [os.getpid()]
    with pytest.raises(installer.InstallFailure) as info:
        installer.Lock(venv).acquire()
    assert "may still be writing" in info.value.remedy
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    installer.Lock(venv).retain([finished.pid])
    if os.name != "nt":
        with pytest.raises(installer.InstallFailure) as info:
            installer.Lock(venv).acquire()
        assert "have exited" in info.value.remedy and "delete" in info.value.remedy


def test_lock_in_unwritable_parent_is_destination_unwritable(installer, tmp_path):
    missing = str(tmp_path / "missing-parent" / "env")
    with pytest.raises(installer.InstallFailure) as info:
        installer.Lock(missing).acquire()
    assert info.value.code == "destination_unwritable" and info.value.retryable is False
    assert "writable --venv" in info.value.remedy


def test_reservation_publish_is_atomic_unique_and_exclusive(installer, tmp_path):
    venv = str(tmp_path / "env")
    res = installer.Reservation(venv)
    assert res.read() is None
    res.publish({"pid": 1, "created": "t"})
    assert res.read()["installer"] == "snaplii-install" and res.read()["schema"] == 1
    assert res.leftovers() == []
    with pytest.raises(FileExistsError):
        res.publish({"pid": 2, "created": "t"})
    res.publish({"pid": 3, "created": "t", "identity": [1, 2]}, update=True)
    assert res.read()["identity"] == [1, 2]
    res.remove()
    assert res.read() is None


def test_reservation_foreign_file_and_leftovers(installer, tmp_path):
    venv = str(tmp_path / "env")
    res = installer.Reservation(venv)
    open(res.path, "w").write("not json")
    with pytest.raises(installer.ForeignFile):
        res.read()
    os.remove(res.path)
    open(res.path, "w").write(json.dumps({"installer": "someone-else", "schema": 1}))
    with pytest.raises(installer.ForeignFile):
        res.read()
    leftover = tmp_path / "env.creating.abc123.tmp"
    leftover.write_text("{}")
    assert res.leftovers() == [str(leftover)]
    res2 = installer.Reservation(venv)
    os.remove(res.path)
    res2.publish({"pid": 9, "created": "t"})
    assert leftover.exists() and leftover.read_text() == "{}"   # never reused or removed


def test_reservation_link_refused_by_filesystem_is_destination_unwritable(installer, tmp_path, monkeypatch):
    def refuse(src, dst):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(installer.os, "link", refuse)
    with pytest.raises(installer.InstallFailure) as info:
        installer.Reservation(str(tmp_path / "env")).publish({"pid": 1, "created": "t"})
    assert info.value.code == "destination_unwritable"


def _marker(venv):
    os.makedirs(venv, exist_ok=True)
    open(os.path.join(venv, "snaplii-installer.json"), "w").write(
        json.dumps({"installer": "snaplii-install", "schema": 1, "python": "x", "created": "t", "installer_version": "1"}))


def test_classify_new_ours_and_foreign(installer, tmp_path):
    venv = str(tmp_path / "env")
    res = installer.Reservation(venv)
    warnings = []
    assert installer.classify_destination(venv, res, False, warnings) == "new"
    os.makedirs(venv)
    with pytest.raises(installer.InstallFailure) as info:
        installer.classify_destination(venv, res, False, warnings)
    assert info.value.code == "venv_path_occupied"
    _marker(venv)
    assert installer.classify_destination(venv, res, False, warnings) == "ours"


def test_classify_removes_our_leftover_reservation_beside_a_marked_env_but_not_in_check_mode(installer, tmp_path):
    venv = str(tmp_path / "env")
    _marker(venv)
    res = installer.Reservation(venv)
    res.publish({"pid": 1, "created": "t"})
    warnings = []
    assert installer.classify_destination(venv, res, True, warnings) == "ours"
    assert os.path.exists(res.path) and warnings
    assert installer.classify_destination(venv, res, False, []) == "ours"
    assert not os.path.exists(res.path)
    open(res.path, "w").write("garbage")
    warnings = []
    assert installer.classify_destination(venv, res, False, warnings) == "ours"
    assert os.path.exists(res.path) and any("not written by this installer" in w for w in warnings)


def test_classify_rebuild_windows_and_identity_mismatch(installer, tmp_path):
    venv = str(tmp_path / "env")
    res = installer.Reservation(venv)
    res.publish({"pid": 1, "created": "t"})
    assert installer.classify_destination(venv, res, False, []) == "rebuild"          # state file only
    os.makedirs(venv)
    assert installer.classify_destination(venv, res, False, []) == "rebuild"          # empty dir, no identity
    open(os.path.join(venv, "stray"), "w").write("x")
    with pytest.raises(installer.InstallFailure):
        installer.classify_destination(venv, res, False, [])                          # non-empty, no identity
    res.publish({"pid": 1, "created": "t", "identity": installer.dir_identity(venv)}, update=True)
    assert installer.classify_destination(venv, res, False, []) == "rebuild"          # identity matches
    res.publish({"pid": 1, "created": "t", "identity": [0, 0]}, update=True)
    with pytest.raises(installer.InstallFailure) as info:
        installer.classify_destination(venv, res, False, [])
    assert "identity" in info.value.message
    warnings = []
    leftover = tmp_path / "env.creating.zzz.tmp"
    leftover.write_text("")
    res.publish({"pid": 1, "created": "t", "identity": installer.dir_identity(venv)}, update=True)
    installer.classify_destination(venv, res, False, warnings)
    assert any("leftover temporary file" in w for w in warnings)
