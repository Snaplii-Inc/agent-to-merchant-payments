from __future__ import annotations

import hashlib
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any

from snaplii import auth
from snaplii._config_file import config_lock, read_config, write_config
from snaplii.exceptions import AuthError, ConfigError

_TOKEN_SAFETY_MARGIN = 90
_KEYRING_SERVICE = "snaplii-cli"
_SESSION_KEYS = {"access_token", "token_expires_at", "token_origin",
                 "_session_generation", "_token_digest", "_credential_storage"}


def _keyring_available() -> bool:
    try:
        import keyring
        from keyring.backends import chainer, fail, null

        backend = keyring.get_keyring()
        if isinstance(backend, (fail.Keyring, null.Keyring)):
            return False
        if isinstance(backend, chainer.ChainerBackend):
            return any(not isinstance(child, (fail.Keyring, null.Keyring)) and child.priority > 0
                       for child in backend.backends)
        return backend.priority > 0
    except Exception:
        return False


def _keyring_get(service: str):
    try:
        import keyring
        return keyring.get_password(service, "access_token")
    except Exception:
        return None


def _keyring_set(service: str, token: str) -> bool:
    try:
        import keyring
        keyring.set_password(service, "access_token", token)
        return keyring.get_password(service, "access_token") == token
    except Exception:
        return False


def _keyring_delete(service: str):
    try:
        import keyring
        keyring.delete_password(service, "access_token")
    except Exception:
        # The durable cleared-session marker makes any residue unusable.
        pass


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _cache_error(message: str | None = None, reason_code: str = "session_cache_failed") -> AuthError:
    # Configuration messages are fixed, secret-free strings (a path at most), so
    # the actionable cause is kept instead of a generic replacement.
    return AuthError(message or "The session could not be saved and verified. Authentication is incomplete.",
                     auth_state="session_cache_failed", reason_code=reason_code,
                     next_action={"type": "stop", "reason": "session_cache_failed"})


class ConfigStore:
    # Same-process reuse for MCP, isolated by canonical configuration path.
    _MEM_SECRETS: dict = {}
    _FAILED_KEYRINGS: set = set()
    _NEVER_STORE = {"api_key"}

    def __init__(self, path: Path | None = None, *, runtime: str | None = None):
        self._path = Path(os.path.abspath(path or os.environ.get("SNAPLII_CONFIG_PATH")
                                         or Path.home() / ".snaplii" / "config.json"))
        self._cache_key = str(self._path.resolve())
        self._keyring_service = _KEYRING_SERVICE + ":" + _digest(self._cache_key)
        self._use_keyring = self._cache_key not in self._FAILED_KEYRINGS and _keyring_available()
        self._muse = auth.detect_muse()
        # "cli": a one-shot process that cannot keep a memory-only session.
        # "mcp": a long-lived process whose memory session only it can renew.
        self.runtime = runtime

    @property
    def path(self) -> Path:
        return self._path

    def _selected_storage(self, data: dict) -> str:
        if self._muse.detected:
            return "config file"
        if self._use_keyring and self._cache_key not in self._FAILED_KEYRINGS:
            return "system keychain"
        if (os.environ.get("SNAPLII_ALLOW_INSECURE", "").strip().lower() in ("1", "true", "yes", "on")
                or data.get("allow_insecure_mode") is True):
            return "config file"
        return "process memory"

    def _session_token(self, data: dict):
        storage = data.get("_credential_storage")
        if storage == "config file":
            token = data.get("access_token")
        elif storage == "process memory":
            memory = self._MEM_SECRETS.get(self._cache_key, {})
            token = memory.get("access_token") if memory.get("_session_generation") == data.get("_session_generation") else None
        elif storage == "system keychain":
            token = _keyring_get(self._keyring_service)
        elif storage == "cleared":
            return None
        else:
            # A missing expiry/file must never resurrect a residual keyring value.
            if not data.get("token_expires_at"):
                return None
            token = data.get("access_token")
            if self._use_keyring:
                token = _keyring_get(_KEYRING_SERVICE) or token
        if not isinstance(token, str) or not token.strip():
            return None
        expected = data.get("_token_digest")
        if storage and (not expected or expected != _digest(token)):
            return None
        return token

    def load(self) -> dict:
        data = read_config(self._path)
        token = self._session_token(data)
        data.pop("api_key", None)
        data.pop("access_token", None)
        if token is not None:
            data["access_token"] = token
        return data

    def get(self, key: str, default: Any = None) -> Any:
        return self.load().get(key, default)

    def save(self, data: dict) -> None:
        # A stale load/save must not roll a newer committed session back.
        with config_lock(self._path):
            current = read_config(self._path)
            updates = dict(data)
            if ("_session_generation" in updates
                    and updates["_session_generation"] != current.get("_session_generation")):
                for key in _SESSION_KEYS | {"agent_id", "auth_method", "country"}:
                    updates.pop(key, None)
            self._update(current, updates)

    def set(self, key: str, value: Any) -> None:
        if key not in self._NEVER_STORE:
            self.set_many({key: value})

    def set_many(self, updates: dict) -> None:
        with config_lock(self._path):
            self._update(read_config(self._path), updates)

    def _update(self, data: dict, updates: dict):
        token = updates.get("access_token")
        data.update({k: v for k, v in updates.items()
                     if k not in self._NEVER_STORE and k != "access_token"})
        data.pop("api_key", None)
        if isinstance(token, str) and token.strip():
            self._store_session(data, token)
        else:
            # None or empty never stores or clears a secret (the legacy save() idiom).
            write_config(self._path, data, private="access_token" in data)

    @staticmethod
    def _validate_token(token, expires_in) -> int:
        if isinstance(expires_in, float) and math.isfinite(expires_in) and expires_in.is_integer():
            expires_in = int(expires_in)  # JSON numbers may arrive as 604800.0
        if (not isinstance(token, str) or not token.strip() or type(expires_in) is not int
                or expires_in <= _TOKEN_SAFETY_MARGIN):
            raise AuthError("Login did not return a usable access token and expiry.",
                            auth_state="auth_response_invalid", reason_code="invalid_token_or_expiry",
                            next_action={"type": "stop", "reason": "auth_response_invalid"})
        return expires_in

    def _store_session(self, data: dict, token: str):
        storage = self._selected_storage(data)
        previous_keychain = None
        if storage == "system keychain":
            previous_keychain = _keyring_get(self._keyring_service)
            if not _keyring_set(self._keyring_service, token):
                self._use_keyring = False
                self._FAILED_KEYRINGS.add(self._cache_key)
                storage = self._selected_storage(data)
        if storage == "process memory" and self.runtime == "cli":
            raise AuthError(
                "No usable keyring was found and file storage is not enabled, so a later "
                "command could not reuse this session. Set SNAPLII_ALLOW_INSECURE=1 (or "
                "allow_insecure_mode=true in config.json) to keep the token in the "
                "owner-only config file, or install a keyring backend.",
                auth_state="session_cache_failed", reason_code="no_persistent_storage",
                next_action={"type": "stop", "reason": "session_cache_failed"})
        data = {k: v for k, v in data.items() if k not in {"api_key", "access_token"}}
        data.update(_session_generation=uuid.uuid4().hex, _token_digest=_digest(token),
                    _credential_storage=storage)
        if storage == "config file":
            data["access_token"] = token
        metadata_committed = False
        try:
            write_config(self._path, data, private=storage == "config file")
            metadata_committed = True
            persisted = read_config(self._path)
            if persisted != data:
                raise _cache_error()
            if storage == "process memory":
                self._MEM_SECRETS[self._cache_key] = {**data, "access_token": token}
            else:
                self._MEM_SECRETS.pop(self._cache_key, None)
            if self._session_token(persisted) != token:
                raise _cache_error()
        except ConfigError as exc:
            if storage == "system keychain" and not metadata_committed:
                # Restore the old secret only if the atomic metadata write failed.
                # After commit, keep the new pair even if verification fails;
                # restoring only the secret would invalidate the stored session.
                if previous_keychain:
                    _keyring_set(self._keyring_service, previous_keychain)
                else:
                    _keyring_delete(self._keyring_service)
            raise _cache_error(exc.message) from None

    def commit_session(self, access_token: str, expires_in: int, *, agent_id,
                       auth_method: str, token_origin: str, country=None):
        expires_in = self._validate_token(access_token, expires_in)
        origin = auth.normalize_origin(token_origin)
        if auth_method not in ("vault", "api_key", "url"):
            raise ConfigError("Unsupported authentication method.")
        if agent_id is not None and not auth.valid_agent_id(agent_id):
            raise ConfigError("Invalid agent ID.")
        try:
            with config_lock(self._path):
                data = read_config(self._path)
                for key in ("agent_id", "country"):
                    data.pop(key, None)
                if agent_id is not None:
                    data["agent_id"] = agent_id
                if isinstance(country, str) and country.upper() in ("CA", "US"):
                    data["country"] = country.upper()
                data.update(token_expires_at=time.time() + expires_in, auth_method=auth_method,
                            token_origin=origin)
                self._store_session(data, access_token)
        except ConfigError as exc:
            if isinstance(exc, AuthError):
                raise
            raise _cache_error(exc.message) from None

    def cache_token(self, access_token: str, expires_in: int) -> None:
        expires_in = self._validate_token(access_token, expires_in)
        self.set_many({"access_token": access_token, "token_expires_at": time.time() + expires_in})

    def _valid_token(self, data: dict, *, origin=None):
        token = self._session_token(data)
        expires_at = data.get("token_expires_at")
        if (not token or type(expires_at) not in (int, float) or not math.isfinite(expires_at)
                or time.time() >= expires_at - _TOKEN_SAFETY_MARGIN):
            return None
        if origin is not None and data.get("token_origin") not in (None, auth.normalize_origin(origin)):
            return None
        return token

    def get_cached_token(self, *, origin=None) -> str | None:
        return self._valid_token(read_config(self._path), origin=origin)

    def clear_token(self, *, expected_token=None) -> bool:
        with config_lock(self._path):
            data = read_config(self._path)
            if expected_token is not None and self._session_token(data) != expected_token:
                return False
            for key in _SESSION_KEYS | {"api_key"}:
                data.pop(key, None)
            data["_credential_storage"] = "cleared"
            write_config(self._path, data)
            self._MEM_SECRETS.pop(self._cache_key, None)
            _keyring_delete(self._keyring_service)
            # A pre-0.17 keychain item is removed whether or not this
            # configuration still points at it.
            _keyring_delete(_KEYRING_SERVICE)
            return True

    def clear(self) -> None:
        with config_lock(self._path):
            # Explicit config clear removes corrupt JSON too; symlink checks are
            # already enforced by config_lock. Remove metadata first: a failed
            # keyring delete cannot resurrect it.
            if self._path.exists():
                self._path.unlink()
            self._MEM_SECRETS.pop(self._cache_key, None)
            _keyring_delete(self._keyring_service)
            _keyring_delete(_KEYRING_SERVICE)
        # Keep the empty lock inode: a waiter may already have it open. Unlinking
        # it would let another writer create and acquire a different lock.

    def auth_status(self, *, origin: str) -> dict:
        base_url = auth.normalize_base_url(origin)
        origin = auth.normalize_origin(origin)
        data = read_config(self._path)
        token = self._valid_token(data, origin=origin)
        method = data.get("auth_method")
        if method not in ("api_key", "vault", "url"):
            method = None
        state = "ready" if token else "reauth_required" if method or data.get("token_expires_at") else "auth_required"
        host = "muse" if self._muse.detected else "unknown"
        storage = data.get("_credential_storage") if self._session_token(data) else None
        if storage not in ("config file", "system keychain", "process memory"):
            storage = self._selected_storage(data)
        action = auth.build_auth_action(state, host=host, auth_method=method, origin=base_url)
        mcp_recovery = storage == "process memory" or (storage == "system keychain" and method != "vault")
        if (self.runtime == "mcp" and host == "unknown" and mcp_recovery
                and action is not None and action.get("type") == "run_cli"):
            # Memory sessions require this process; keychain-backed MCP hosts
            # may also lack a shell. Preserve explicitly selected secure auth.
            action = {"type": "call_mcp_tool", "tool": "snaplii_connect", "arguments": {}}
        result = {"has_valid_token": bool(token), "auth_state": state, "host": host,
                  "auth_method": method, "credential_storage": storage, "base_url": base_url,
                  "next_action": action}
        if auth.valid_agent_id(data.get("agent_id")):
            result["agent_id"] = data["agent_id"]
        if data.get("country") in ("US", "CA"):
            result["country"] = data["country"]
        return result
