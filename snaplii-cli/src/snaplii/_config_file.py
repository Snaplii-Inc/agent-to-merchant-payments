"""Private, short-lived locks and atomic writes for one configuration path."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from snaplii.exceptions import ConfigError

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_LOCK_TIMEOUT = 5.0


def _reject_symlink(path: Path):
    """The configuration file and its lock must be regular files, never links."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode):
        raise ConfigError(f"Configuration file must be a regular file, not a symlink: {path}")


def is_private(path: Path) -> bool:
    """True when only the owner can read or write the file (always on Windows)."""
    if os.name == "nt":
        return True
    return stat.S_IMODE(os.stat(path).st_mode) & 0o077 == 0


def lock_file(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


def read_config(path: Path) -> dict:
    try:
        _reject_symlink(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ConfigError("Cannot read configuration. Check file permissions and JSON format.") from None


def write_config(path: Path, data: dict, *, private: bool = False):
    """Caller holds config_lock; the old file survives a failed replace.

    With private=True the new file must be owner-only before any secret byte is
    written, so a mount that ignores file modes fails closed instead of leaving
    a token world-readable.
    """
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".snaplii-", suffix=".tmp", dir=path.parent)
        if private and not is_private(Path(temporary)):
            os.close(fd)
            raise ConfigError(
                f"Configuration file {path} cannot be made private on this filesystem, "
                "so the session token was not saved. Use a location that supports "
                "owner-only file permissions.")
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            # mkstemp creates a private file before any secret bytes are written.
            json.dump(data, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except ConfigError:
        raise
    except (OSError, ValueError, TypeError):
        raise ConfigError("Cannot save configuration securely. Previous configuration was not replaced.") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _make_directory(path: Path):
    missing = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700, exist_ok=True)
    # A symlinked directory (stow, chezmoi, ostree /home, macOS /var) is followed
    # to its target; only the configuration file itself may not be a link.
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise ConfigError(f"Configuration directory is not a directory: {path}")
    # Repair stray group/other write bits left by an older release or a wide
    # umask instead of refusing every command; the token file is checked
    # separately when a secret is written.
    mode = stat.S_IMODE(info.st_mode)
    if (os.name != "nt" and mode & 0o022
            and (not hasattr(os, "geteuid") or info.st_uid == os.geteuid())):
        try:
            os.chmod(path, mode & ~0o022)
        except OSError:
            pass


@contextmanager
def config_lock(path: Path):
    """Serialize threads and processes; never unlink the lock inode while held."""
    key = str(Path(os.path.abspath(path)).resolve())
    with _LOCKS_GUARD:
        local = _LOCKS.setdefault(key, threading.Lock())
    if not local.acquire(timeout=_LOCK_TIMEOUT):
        raise ConfigError("Configuration is busy. Retry after the other command completes.")
    descriptor = None
    try:
        _make_directory(path.parent)
        _reject_symlink(path)
        lock_path = lock_file(path)
        _reject_symlink(lock_path)
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        if os.name == "nt":
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
        else:
            import fcntl
        deadline = time.monotonic() + _LOCK_TIMEOUT
        while True:
            try:
                if os.name == "nt":
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ConfigError("Configuration is busy. Retry after the other command completes.") from None
                time.sleep(0.025)
        yield
    except OSError:
        raise ConfigError("Cannot access configuration securely. Check directory permissions.") from None
    finally:
        try:
            if descriptor is not None:
                # Closing the descriptor releases its OS lock, even on an
                # exceptional exit. Keep the in-process lock until it is closed.
                os.close(descriptor)
        finally:
            local.release()
