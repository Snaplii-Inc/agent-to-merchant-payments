import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


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
