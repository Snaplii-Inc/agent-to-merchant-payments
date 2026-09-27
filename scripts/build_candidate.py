#!/usr/bin/env python3
"""Build a local CLI/MCP + skill candidate bundle. Never commit, publish, or log in."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="New directory; defaults to dist/muse-candidate-VERSION")
    args = parser.parse_args(argv)
    with (ROOT / "snaplii-cli/pyproject.toml").open("rb") as stream:
        cli = tomllib.load(stream)["project"]
    with (ROOT / "mcp-server/pyproject.toml").open("rb") as stream:
        mcp = tomllib.load(stream)["project"]
    version = cli["version"]
    if (not re.fullmatch(r"\d+\.\d+\.\d+rc\d+", version) or mcp["version"] != version
            or f"snaplii-cli>={version}" not in mcp["dependencies"]):
        parser.error("CLI/MCP must have the same rc version and matching CLI dependency floor")
    output = (args.output_dir or ROOT / "dist" / ("muse-candidate-" + version)).absolute()
    # Append rather than with_suffix: versions contain dots.
    archive = Path(str(output) + ".zip")
    if output.exists() or output.is_symlink() or archive.exists():
        parser.error("Output already exists; choose a new --output-dir")
    run(sys.executable, ROOT / "scripts/sync_muse_auth_docs.py", "--check")
    output.mkdir(parents=True)
    for project in ("snaplii-cli", "mcp-server"):
        run("uv", "build", ROOT / project, "--wheel", "--out-dir", output / "wheels")
    copies = {
        "scripts/install_candidate.py": "install.py",
        "scripts/candidate/INSTALL.md": "INSTALL.md",
        "clawhub-publish/SKILL.md": "skills/snaplii-cli/SKILL.md",
        "clawhub-autopilot/SKILL.md": "skills/snaplii-autopilot/SKILL.md",
    }
    for source, target in copies.items():
        destination = output / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source, destination)
    run(sys.executable, ROOT / "scripts/sync_muse_auth_docs.py", "--check",
        "--skill", output / "skills/snaplii-cli/SKILL.md",
        "--skill", output / "skills/snaplii-autopilot/SKILL.md")
    payload = sorted(path for path in output.rglob("*") if path.is_file())
    manifest = {
        "version": version,
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "working_tree_modified": subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=ROOT).returncode != 0,
        "sha256": {path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in payload},
    }
    manifest_path = output / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    run(sys.executable, output / "install.py", "--verify-only")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in [*payload, manifest_path]:
            bundle.write(path, arcname=output.name + "/" + path.relative_to(output).as_posix())
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    Path(str(archive) + ".sha256").write_text(checksum + "  " + archive.name + "\n", encoding="utf-8")
    print(json.dumps({"bundle": str(archive), "sha256": checksum, "version": version}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
