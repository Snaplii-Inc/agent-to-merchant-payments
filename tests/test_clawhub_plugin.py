import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "clawhub-plugin"


def _json(relative):
    return json.loads((PLUGIN / relative).read_text())


def test_manifests_name_and_version_the_same_package():
    package = _json("package.json")
    claude = _json(".claude-plugin/plugin.json")
    native = _json("openclaw.plugin.json")
    assert package["name"] == claude["name"] == native["name"] == "snaplii-a2m-mcp"
    assert package["version"] == claude["version"] == native["version"]


def test_package_declares_compatibility_but_stays_a_bundle():
    openclaw = _json("package.json")["openclaw"]
    assert openclaw["compat"]["pluginApi"]
    assert openclaw["build"]["openclawVersion"]
    # A runtime entrypoint would make OpenClaw load this as a native code
    # plugin; the package has no code, only the MCP server in .mcp.json.
    assert "extensions" not in openclaw and "runtimeExtensions" not in openclaw
