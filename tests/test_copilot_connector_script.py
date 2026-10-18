"""Runs the .NET harness for copilot-connector/script.csx when a .NET SDK is installed."""
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent / "copilot_connector" / "Harness"


@pytest.mark.skipif(shutil.which("dotnet") is None, reason="needs the .NET 8 SDK")
def test_connector_script_against_a_fake_gateway():
    run = subprocess.run(["dotnet", "run", "--project", str(HARNESS)], capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "ALL PASSED" in run.stdout
