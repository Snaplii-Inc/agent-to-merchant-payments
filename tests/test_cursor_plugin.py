import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "cursor-plugin"


def test_plugin_variable_reaches_the_mcp_server_env():
    manifest = json.loads((PLUGIN / ".cursor-plugin" / "plugin.json").read_text())
    mcp = json.loads((PLUGIN / "mcp.json").read_text())
    variables = manifest["variables"]["properties"]
    assert set(variables) == {"SNAPLII_API_KEY"}
    assert "SNAPLII_API_KEY" not in manifest["variables"].get("required", [])
    env = mcp["mcpServers"]["snaplii"]["env"]
    # Optional: an empty default, never an unexpanded placeholder, reaches the server.
    assert env == {"SNAPLII_API_KEY": "${SNAPLII_API_KEY:-}"}
