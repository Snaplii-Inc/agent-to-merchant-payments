#!/usr/bin/env python3
"""One-command Claude Desktop setup for the Snaplii MCP server.

For users who cloned the repo: this registers the Snaplii MCP server in your
Claude Desktop config (merging, not overwriting), so you don't hand-edit JSON.

    python3 scripts/setup_claude_desktop.py

Then fully quit and reopen Claude Desktop. Claude Desktop cannot auto-discover a
folder — it loads MCP servers from its config file — so this script does that
registration for you.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def config_path() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", home)) / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    server_py = repo_root / "mcp-server" / "server.py"
    if not server_py.exists():
        print(f"ERROR: cannot find {server_py}. Run this from a cloned repo.")
        return 1

    # Verify the running interpreter can import the deps; guide if not.
    try:
        import mcp  # noqa: F401
        sys.path.insert(0, str(repo_root / "snaplii-cli" / "src"))
        import snaplii  # noqa: F401
    except Exception:
        print("ERROR: this Python is missing dependencies. Install them first:")
        print(f"  {sys.executable} -m pip install -e ./snaplii-cli 'mcp[cli]'")
        print("then re-run this script with the SAME python.")
        return 1

    cfg_path = config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
        except Exception:
            backup = cfg_path.with_suffix(".json.bak")
            cfg_path.rename(backup)
            print(f"WARNING: existing config was invalid JSON; backed up to {backup}")
            cfg = {}

    servers = cfg.setdefault("mcpServers", {})
    servers["snaplii"] = {"command": sys.executable, "args": [str(server_py)]}

    if cfg_path.exists():
        cfg_path.replace(cfg_path.with_suffix(".json.bak"))  # backup before write
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")

    print("✓ Registered the Snaplii MCP server in Claude Desktop:")
    print(f"    config:  {cfg_path}")
    print(f"    python:  {sys.executable}")
    print(f"    server:  {server_py}")
    print("\nNext: fully quit Claude Desktop (Cmd+Q) and reopen it.")
    print("Then authenticate once:  snaplii init   (or ask Claude to run snaplii_init).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
