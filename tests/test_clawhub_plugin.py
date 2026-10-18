import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "clawhub-plugin"


def _json(relative):
    return json.loads((PLUGIN / relative).read_text())


def test_manifests_name_and_version_the_same_package():
    package = _json("package.json")
    claude = _json(".claude-plugin/plugin.json")
    native = _json("openclaw.plugin.json")
    assert package["name"] == claude["name"] == native["id"] == "snaplii-a2m-mcp"
    assert package["version"] == claude["version"] == native["version"]


def test_native_manifest_has_what_the_clawhub_scan_reads():
    # ClawHub reads openclaw.plugin.json, so it needs an id and a configSchema,
    # and OpenClaw uses this manifest instead of the bundle files: it must
    # start the same MCP server as .mcp.json.
    native = _json("openclaw.plugin.json")
    assert set(native) <= {"id", "name", "description", "version", "mcpServers", "configSchema"}
    assert native["configSchema"] == {"type": "object", "additionalProperties": False, "properties": {}}
    bundle = _json(".mcp.json")["mcpServers"]["snaplii"]
    server = native["mcpServers"]["snaplii"]
    assert server["transport"] == "stdio"
    assert (server["command"], server["args"]) == (bundle["command"], bundle["args"])


def test_package_declares_compatibility_but_stays_a_bundle():
    openclaw = _json("package.json")["openclaw"]
    assert openclaw["compat"]["pluginApi"]
    assert openclaw["build"]["openclawVersion"]
    # The package has no code, so it declares no runtime entrypoint; its only
    # capability is the MCP server in the manifests.
    assert "extensions" not in openclaw and "runtimeExtensions" not in openclaw
