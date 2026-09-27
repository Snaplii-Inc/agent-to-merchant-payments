import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest


INSTALLER = Path(__file__).resolve().parents[1] / "scripts" / "install_candidate.py"


def test_bundle_verification_detects_tampering_before_creating_an_environment(tmp_path):
    installer = tmp_path / "install.py"
    shutil.copyfile(INSTALLER, installer)
    payload = tmp_path / "wheels" / "snaplii_cli-0.17.0rc1-py3-none-any.whl"
    payload.parent.mkdir()
    payload.write_bytes(b"synthetic wheel payload; verification test only")
    hashes = {str(path.relative_to(tmp_path)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (installer, payload)}
    (tmp_path / "MANIFEST.json").write_text(json.dumps({"version": "0.17.0rc1", "sha256": hashes}))
    result = subprocess.run([sys.executable, str(installer), "--verify-only"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "verified"
    payload.write_bytes(b"modified")
    result = subprocess.run([sys.executable, str(installer)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "checksum" in result.stderr.lower()
    assert not (tmp_path / ".venv").exists()


def test_manifest_cannot_read_outside_the_bundle(tmp_path):
    installer = tmp_path / "install.py"
    shutil.copyfile(INSTALLER, installer)
    (tmp_path / "MANIFEST.json").write_text(json.dumps({"version": "0.17.0rc1", "sha256": {"../outside": "0" * 64}}))
    result = subprocess.run([sys.executable, str(installer), "--verify-only"], capture_output=True, text=True)
    assert result.returncode != 0
    assert "path" in result.stderr.lower()


@pytest.mark.skipif(sys.version_info < (3, 11), reason="The candidate builder requires Python 3.11+ (tomllib)")
def test_built_candidate_contains_only_delivery_files_and_no_dialog_status(tmp_path, monkeypatch):
    root = INSTALLER.parents[1]
    spec = importlib.util.spec_from_file_location("candidate_builder", root / "scripts/build_candidate.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    run = builder.run
    load = builder.tomllib.load

    def candidate_metadata(stream):
        # Candidate packaging must remain testable after the repository moves
        # to a stable release, without relaxing its RC-only version guard.
        metadata = load(stream)
        metadata["project"]["version"] = "0.17.0rc1"
        if metadata["project"]["name"] == "snaplii-mcp":
            metadata["project"]["dependencies"] = ["snaplii-cli>=0.17.0rc1"]
        return metadata

    monkeypatch.setattr(builder, "tomllib", SimpleNamespace(load=candidate_metadata))

    def build_fixture_wheels(*args):
        # Exercise the real manifest, copy, sync, checksum and archive pipeline
        # without downloading dependencies or installing/authenticating anything.
        if args[0] != "uv":
            return run(*args)
        project = Path(args[2])
        with (project / "pyproject.toml").open("rb") as stream:
            metadata = builder.tomllib.load(stream)["project"]
        destination = Path(args[-1])
        destination.mkdir(parents=True, exist_ok=True)
        name = metadata["name"].replace("-", "_")
        with zipfile.ZipFile(destination / f"{name}-{metadata['version']}-py3-none-any.whl", "w") as wheel:
            wheel.writestr("fixture.txt", "Synthetic build test; not an installable package.")

    monkeypatch.setattr(builder, "run", build_fixture_wheels)
    output = tmp_path / "candidate"
    assert builder.main(["--output-dir", str(output)]) == 0
    archive = Path(str(output) + ".zip")
    manifest = json.loads((output / "MANIFEST.json").read_text())
    assert set(manifest) == {"version", "source_revision", "working_tree_modified", "sha256"}
    version = manifest["version"]
    expected = {
        "install.py", "INSTALL.md", "skills/snaplii-cli/SKILL.md",
        "skills/snaplii-autopilot/SKILL.md",
        f"wheels/snaplii_cli-{version}-py3-none-any.whl",
        f"wheels/snaplii_mcp-{version}-py3-none-any.whl",
    }
    assert set(manifest["sha256"]) == expected
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {f"candidate/{name}" for name in expected | {"MANIFEST.json"}}
        for name in expected | {"MANIFEST.json"}:
            payload = bundle.read(f"candidate/{name}")
            if name in expected:
                assert hashlib.sha256(payload).hexdigest() == manifest["sha256"][name]
            if not name.endswith(".whl"):
                text = payload.decode("utf-8")
                assert "muse_dialog_acceptance" not in text
                assert "muse_native_dialog" not in text
                assert "Muse 自动输入框的真实效果仍待" not in text
                assert "弹窗效果待验证" not in text
    assert Path(str(archive) + ".sha256").read_text().split()[0] == hashlib.sha256(archive.read_bytes()).hexdigest()
