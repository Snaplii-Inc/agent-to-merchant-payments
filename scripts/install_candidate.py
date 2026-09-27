#!/usr/bin/env python3
"""Verify and install a matched candidate in a new virtual environment; never log in."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import venv


def verify(bundle: Path) -> dict:
    manifest = json.loads((bundle / "MANIFEST.json").read_text(encoding="utf-8"))
    if not re.fullmatch(r"\d+\.\d+\.\d+rc\d+", manifest["version"]):
        raise ValueError("Expected a release-candidate version")
    hashes = manifest["sha256"]
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Missing payload checksums")
    for name, expected in hashes.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ValueError("Invalid manifest path")
        path = bundle / relative
        if (not path.is_file() or path.is_symlink() or bundle not in path.resolve().parents):
            raise ValueError("Missing or unsafe payload path: " + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Payload checksum mismatch: " + name)
    return manifest


def main(argv=None) -> int:
    bundle = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--venv", type=Path, default=bundle / ".venv", help="New environment; existing paths are refused")
    parser.add_argument("--with-mcp", action="store_true", help="Also install MCP (Python 3.10+)")
    args = parser.parse_args(argv)
    try:
        manifest = verify(bundle)
        version = manifest["version"]
        if args.verify_only:
            print(json.dumps({"status": "verified", "version": version, "files": len(manifest["sha256"])}))
            return 0
        if sys.version_info < ((3, 10) if args.with_mcp else (3, 9)):
            raise ValueError("Use Python 3.9+ for CLI, or Python 3.10+ with MCP")
        destination = args.venv.expanduser().absolute()
        if destination.exists() or destination.is_symlink():
            raise ValueError("Environment already exists; choose a new --venv path (nothing was overwritten)")
        packages = ["snaplii_cli"] + (["snaplii_mcp"] if args.with_mcp else [])
        wheels = [f"wheels/{name}-{version}-py3-none-any.whl" for name in packages]
        if any(name not in manifest["sha256"] for name in wheels):
            raise ValueError("Required wheel is missing from the checksum manifest")
        venv.EnvBuilder(with_pip=True).create(destination)
        binary_dir = destination / ("Scripts" if os.name == "nt" else "bin")
        python = binary_dir / ("python.exe" if os.name == "nt" else "python")
        subprocess.run([str(python), "-m", "pip", "--disable-pip-version-check", "install",
                        "--prefer-binary", "--timeout", "30", "--retries", "1",
                        *[str(bundle / name) for name in wheels]], check=True, stdout=sys.stderr)
        subprocess.run([str(python), "-m", "pip", "check"], check=True, stdout=sys.stderr)
        cli = binary_dir / ("snaplii.exe" if os.name == "nt" else "snaplii")
        output = subprocess.check_output([str(cli), "--version"], text=True)
        if output.strip() != "snaplii, version " + version:
            raise ValueError("Installed CLI version does not match the bundle")
        print(json.dumps({"status": "installed", "version": version, "cli": str(cli),
                          "skill": str(bundle / "skills/snaplii-cli/SKILL.md"),
                          "connected": False}, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print("Candidate installation failed: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
