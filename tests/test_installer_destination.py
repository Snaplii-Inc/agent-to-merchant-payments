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
