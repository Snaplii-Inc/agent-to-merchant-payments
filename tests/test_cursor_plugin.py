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


def test_logo_is_a_square_png_without_metadata():
    manifest = json.loads((PLUGIN / ".cursor-plugin" / "plugin.json").read_text())
    data = (PLUGIN / manifest["logo"]).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    assert width == height
    # A colour type without alpha keeps the background plate opaque.
    assert data[25] in (0, 2)
    # Only critical chunks: no XMP, EXIF or text metadata travels with the logo.
    chunks, i = [], 8
    while i < len(data):
        length = int.from_bytes(data[i:i + 4], "big")
        chunks.append(data[i + 4:i + 8])
        i += 12 + length
    assert set(chunks) <= {b"IHDR", b"PLTE", b"IDAT", b"IEND"}
