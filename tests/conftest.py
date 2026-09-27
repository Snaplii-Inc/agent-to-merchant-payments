import sys
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# snaplii package (editable install also works, but be explicit for CI)
sys.path.insert(0, str(ROOT / "snaplii-cli" / "src"))
# mcp-server/server.py is a standalone module, not a package
sys.path.insert(0, str(ROOT / "mcp-server"))


@pytest.fixture
def muse_filesystem(monkeypatch):
    """Synthetic OS metadata at the host boundary; no host detector override."""
    helper = Path("/opt/hatch/skills/skill-creator/bin/dynamic_credentials.py")
    socket = Path("/run/hatch/auth/authd.sock")
    metadata = {str(path): (stat.S_IFDIR | 0o755, 0)
                for target in (helper, socket) for path in target.parents}
    metadata[str(helper)] = (stat.S_IFREG | 0o644, 0)
    metadata[str(socket)] = (stat.S_IFSOCK | 0o660, 0)
    def synthetic_stat(original):
        def probe(path, *args, **kwargs):
            if str(path) not in metadata:
                return original(path, *args, **kwargs)
            value = metadata[str(path)]
            if value is None:
                raise FileNotFoundError
            if isinstance(value, OSError):
                raise value
            mode, owner = value
            return os.stat_result((mode, 1, 1, 1, owner, 0, 0, 0, 0, 0))
        return probe

    monkeypatch.setattr(os, "stat", synthetic_stat(os.stat))
    monkeypatch.setattr(os, "lstat", synthetic_stat(os.lstat))
    monkeypatch.setattr(sys, "platform", "linux")
    return metadata
