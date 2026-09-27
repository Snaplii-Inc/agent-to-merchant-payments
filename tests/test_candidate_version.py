import json
from importlib.metadata import version

from click.testing import CliRunner

from snaplii import __version__, cli, version_check
from snaplii.config_store import ConfigStore


def test_cli_version_matches_installed_distribution():
    assert __version__ == version("snaplii-cli")


def test_candidate_update_never_replaces_the_bundle_with_pypi(tmp_path, monkeypatch, httpx_mock):
    monkeypatch.setenv("SNAPLII_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(cli, "_VERSION", "0.17.0rc1")
    result = CliRunner().invoke(cli.main, ["update"])
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["status"] == "candidate-pinned"
    assert output["version"] == "0.17.0rc1"
    assert httpx_mock.get_requests() == []
    assert not (tmp_path / "config.json").exists()


def test_candidate_does_not_check_for_stable_updates(tmp_path, monkeypatch, httpx_mock):
    monkeypatch.setattr(version_check, "pkg_version", lambda _: "0.17.0rc1")
    assert version_check.check_for_update(ConfigStore(tmp_path / "config.json")) is None
    assert httpx_mock.get_requests() == []
