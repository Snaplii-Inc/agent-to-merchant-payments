from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


_TOKEN_SAFETY_MARGIN = 90  # seconds before expiry to trigger refresh
_KEYRING_SERVICE = "snaplii-cli"

# Secrets stored in system keychain, never in config.json
_SECRET_KEYS = {"access_token"}


def _keyring_available() -> bool:
    try:
        import keyring
        # Test that backend is usable (not the fail backend)
        backend = keyring.get_keyring()
        return "fail" not in type(backend).__name__.lower()
    except Exception:
        return False


def _keyring_set(key: str, value: str) -> None:
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, key, value)
    except Exception:
        pass


def _keyring_get(key: str) -> str | None:
    try:
        import keyring
        return keyring.get_password(_KEYRING_SERVICE, key)
    except Exception:
        return None


def _keyring_delete(key: str) -> None:
    try:
        import keyring
        keyring.delete_password(_KEYRING_SERVICE, key)
    except Exception:
        pass


class ConfigStore:
    # Process-level cache for secrets when no OS keyring is available and the
    # user has NOT opted into insecure on-disk storage. Survives across the many
    # short-lived ConfigStore() instances the MCP server creates per tool call,
    # but not across separate processes (so the CLI re-auths — by design).
    _MEM_SECRETS: dict = {}

    def __init__(self, path: Path | None = None):
        self._path = path or Path.home() / ".snaplii" / "config.json"
        self._use_keyring = _keyring_available()

    def _insecure_persist_ok(self) -> bool:
        """True only when the user opted into insecure on-disk secret storage."""
        if os.environ.get("SNAPLII_ALLOW_INSECURE", "").strip().lower() in (
            "1", "true", "yes", "on"
        ):
            return True
        data = {}
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
            except Exception:
                data = {}
        return bool(data.get("allow_insecure_mode", False))

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict:
        data = {}
        if self._path.exists():
            data = json.loads(self._path.read_text())
        # Merge secrets from keychain
        if self._use_keyring:
            for key in _SECRET_KEYS:
                val = _keyring_get(key)
                if val:
                    data[key] = val
        return data

    # Keys that must NEVER be written to disk
    _NEVER_STORE = {"api_key"}

    def save(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        persist_secret = self._insecure_persist_ok()
        file_data = {}
        for k, v in data.items():
            if k in self._NEVER_STORE:
                continue  # api_key is never stored anywhere
            if k in _SECRET_KEYS:
                if not v:
                    continue
                if self._use_keyring:
                    _keyring_set(k, str(v))
                elif persist_secret:
                    file_data[k] = v  # explicit opt-in: chmod-600 plaintext
                else:
                    ConfigStore._MEM_SECRETS[k] = str(v)  # process memory only
            else:
                file_data[k] = v
        self._path.write_text(json.dumps(file_data, indent=2) + "\n")
        os.chmod(self._path, 0o600)

    def get(self, key: str, default: Any = None) -> Any:
        if key in _SECRET_KEYS:
            if self._use_keyring:
                val = _keyring_get(key)
                if val:
                    return val
            if key in ConfigStore._MEM_SECRETS:
                return ConfigStore._MEM_SECRETS[key]
        return self.load().get(key, default)

    def set(self, key: str, value: Any) -> None:
        if key in self._NEVER_STORE:
            return  # never store api_key, even via set()
        if key in _SECRET_KEYS and self._use_keyring:
            _keyring_set(key, str(value))
        else:
            data = self.load()
            data[key] = value
            self.save(data)

    def set_many(self, updates: dict) -> None:
        data = self.load()
        data.update(updates)
        self.save(data)

    def clear(self) -> None:
        if self._use_keyring:
            for key in _SECRET_KEYS:
                _keyring_delete(key)
        if self._path.exists():
            self._path.unlink()
        for key in _SECRET_KEYS:
            ConfigStore._MEM_SECRETS.pop(key, None)

    def get_cached_token(self) -> str | None:
        token = self.get("access_token")
        data = {}
        if self._path.exists():
            data = json.loads(self._path.read_text())
        expires_at = data.get("token_expires_at")
        if not token or not expires_at:
            return None
        if time.time() >= expires_at - _TOKEN_SAFETY_MARGIN:
            return None
        return token

    def cache_token(self, access_token: str, expires_in: int) -> None:
        self.set_many({
            "access_token": access_token,
            "token_expires_at": time.time() + expires_in,
        })
