import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# snaplii package (editable install also works, but be explicit for CI)
sys.path.insert(0, str(ROOT / "snaplii-cli" / "src"))
# mcp-server/server.py is a standalone module, not a package
sys.path.insert(0, str(ROOT / "mcp-server"))
