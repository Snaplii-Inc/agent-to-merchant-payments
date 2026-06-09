# A2M Payment Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Snaplii payment path safe-by-construction — the agent never holds the API key, never authors the confirmation a user sees, and never authorizes a charge on its own.

**Architecture:** Pure, testable security units live in a new `snaplii/security/` package (mode resolution, quote→token store, canonical confirmation text). The MCP server (`mcp-server/server.py`) and CLI (`snaplii-cli/src/snaplii/commands/`) are thin glue over them. Confirmation uses MCP `elicit_form` bound to canonical gateway quote fields (Approach 1); the `confirmation_token` is the seam for a future gateway-enforced token. Clients without elicitation are BLOCKED unless a default-OFF opt-in switch enables a warned degraded mode.

**Tech Stack:** Python 3.9+, `click` (CLI), `mcp` SDK (server, stdio + elicitation), `httpx` (gateway), `keyring` (token storage), `pytest` + `pytest-httpx` (tests).

---

## File Structure

**New files:**
- `snaplii-cli/src/snaplii/security/__init__.py` — package marker.
- `snaplii-cli/src/snaplii/security/mode.py` — operating-mode resolution + opt-in detection.
- `snaplii-cli/src/snaplii/security/quote_store.py` — in-memory, single-use, TTL quote→token store.
- `snaplii-cli/src/snaplii/security/canonical.py` — build canonical quote record + human confirmation text.
- `tests/conftest.py` — make `snaplii` and the `server` module importable.
- `tests/test_mode.py`, `tests/test_quote_store.py`, `tests/test_canonical.py`, `tests/test_config_store_secrets.py`, `tests/test_server_confirm.py`, `tests/test_cli_purchase_confirm.py`.

**Modified files:**
- `snaplii-cli/src/snaplii/client.py` — `create_order_and_pay` accepts voucher/cashback/specified_voucher so the charge runs under the approved context (Task 11).
- `snaplii-cli/src/snaplii/config_store.py` — kill silent plaintext token fallback; class-level in-memory secret cache; opt-in persistence.
- `mcp-server/server.py` — quote issues token; purchase/init/billpay_pay enforce confirmation via elicitation; mode gating.
- `snaplii-cli/src/snaplii/commands/purchase.py` — interactive confirmation built from a fresh canonical quote; `--yes` bypass.
- `snaplii-cli/src/snaplii/commands/billpay.py` — same confirmation on the pay subcommand.
- `README.md`, `CHANGELOG.md`, `snaplii-cli/pyproject.toml`, `mcp-server/pyproject.toml` — docs + version bump.

All commands below are run from the repo root: `/Users/jsy/Documents/Snaplii/agent-to-merchant-payments`. The Python interpreter is `.venv/bin/python`; pytest is `.venv/bin/pytest`.

---

## Task 1: Bootstrap test infrastructure

**Files:**
- Modify: `snaplii-cli/pyproject.toml` (dev deps)
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Add `pytest-asyncio` to dev deps**

In `snaplii-cli/pyproject.toml`, change the `dev` extra to include async support:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0,<9",
    "pytest-httpx>=0.35,<1",
    "pytest-asyncio>=0.23,<1",
]
```

- [ ] **Step 2: Install dev deps and the MCP SDK into the venv**

Run:
```bash
.venv/bin/pip install -e "snaplii-cli[dev]" mcp
```
Expected: installs `pytest`, `pytest-httpx`, `pytest-asyncio`, and `mcp` (already present) without error.

- [ ] **Step 3: Create `tests/conftest.py`**

This makes the `snaplii` package and the standalone `server.py` module importable from tests.

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# snaplii package (editable install also works, but be explicit for CI)
sys.path.insert(0, str(ROOT / "snaplii-cli" / "src"))
# mcp-server/server.py is a standalone module, not a package
sys.path.insert(0, str(ROOT / "mcp-server"))
```

- [ ] **Step 4: Create a smoke test `tests/test_smoke.py`**

```python
def test_snaplii_imports():
    import snaplii  # noqa: F401


def test_server_imports():
    import server  # noqa: F401
    assert hasattr(server, "call_tool")
```

- [ ] **Step 5: Run the smoke test**

Run: `.venv/bin/pytest tests/test_smoke.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add snaplii-cli/pyproject.toml tests/conftest.py tests/test_smoke.py
git commit -m "test: bootstrap pytest infrastructure"
```

---

## Task 2: Mode resolution (`security/mode.py`)

**Files:**
- Create: `snaplii-cli/src/snaplii/security/__init__.py`
- Create: `snaplii-cli/src/snaplii/security/mode.py`
- Test: `tests/test_mode.py`

- [ ] **Step 1: Create the package marker**

Create `snaplii-cli/src/snaplii/security/__init__.py` with a single line:

```python
"""Security primitives shared by the Snaplii CLI and MCP server."""
```

- [ ] **Step 2: Write the failing test `tests/test_mode.py`**

```python
from snaplii.security import mode


class FakeStore:
    def __init__(self, data=None):
        self._data = data or {}

    def get(self, key, default=None):
        return self._data.get(key, default)


def test_resolve_mode_elicitation_wins():
    assert mode.resolve_mode(True, False) == mode.ELICITATION
    assert mode.resolve_mode(True, True) == mode.ELICITATION


def test_resolve_mode_degraded_when_opt_in():
    assert mode.resolve_mode(False, True) == mode.DEGRADED


def test_resolve_mode_blocked_by_default():
    assert mode.resolve_mode(False, False) == mode.BLOCKED


def test_opt_in_via_env():
    assert mode.insecure_opt_in_enabled(FakeStore(), env={"SNAPLII_ALLOW_INSECURE": "1"})
    assert mode.insecure_opt_in_enabled(FakeStore(), env={"SNAPLII_ALLOW_INSECURE": "true"})
    assert not mode.insecure_opt_in_enabled(FakeStore(), env={"SNAPLII_ALLOW_INSECURE": "0"})


def test_opt_in_via_config_flag():
    assert mode.insecure_opt_in_enabled(FakeStore({"allow_insecure_mode": True}), env={})
    assert not mode.insecure_opt_in_enabled(FakeStore({}), env={})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_mode.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snaplii.security.mode'`.

- [ ] **Step 4: Write `snaplii-cli/src/snaplii/security/mode.py`**

```python
"""Resolve which security mode a request runs in, and detect the opt-in switch."""

from __future__ import annotations

import os

ELICITATION = "ELICITATION"
DEGRADED = "DEGRADED"
BLOCKED = "BLOCKED"

_TRUE_VALUES = {"1", "true", "yes", "on"}


def resolve_mode(elicitation_supported: bool, insecure_opt_in: bool) -> str:
    """ELICITATION if the client can confirm securely; else DEGRADED only when the
    user explicitly opted in; otherwise BLOCKED (the safe default)."""
    if elicitation_supported:
        return ELICITATION
    if insecure_opt_in:
        return DEGRADED
    return BLOCKED


def insecure_opt_in_enabled(store, env=None) -> bool:
    """True only if the user opted into insecure/degraded behavior, via the
    SNAPLII_ALLOW_INSECURE env var or the allow_insecure_mode config flag."""
    env = os.environ if env is None else env
    if str(env.get("SNAPLII_ALLOW_INSECURE", "")).strip().lower() in _TRUE_VALUES:
        return True
    return bool(store.get("allow_insecure_mode", False))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_mode.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add snaplii-cli/src/snaplii/security/__init__.py snaplii-cli/src/snaplii/security/mode.py tests/test_mode.py
git commit -m "feat: security mode resolution + opt-in detection"
```

---

## Task 3: Quote→token store (`security/quote_store.py`)

**Files:**
- Create: `snaplii-cli/src/snaplii/security/quote_store.py`
- Test: `tests/test_quote_store.py`

- [ ] **Step 1: Write the failing test `tests/test_quote_store.py`**

```python
import pytest

from snaplii.security.quote_store import QuoteStore


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_issue_and_validate_roundtrip():
    store = QuoteStore(ttl_seconds=300, clock=Clock())
    token = store.issue("ITEM-1", "50", {"you_pay": "46"})
    rec = store.validate(token, "ITEM-1", "50")
    assert rec.canonical == {"you_pay": "46"}


def test_expired_token_is_rejected():
    clock = Clock()
    store = QuoteStore(ttl_seconds=300, clock=clock)
    token = store.issue("ITEM-1", "50", {})
    clock.t += 301
    with pytest.raises(ValueError, match="expired"):
        store.validate(token, "ITEM-1", "50")


def test_single_use_after_consume():
    store = QuoteStore(ttl_seconds=300, clock=Clock())
    token = store.issue("ITEM-1", "50", {})
    store.validate(token, "ITEM-1", "50")  # still valid before consume
    store.consume(token)
    with pytest.raises(ValueError, match="used"):
        store.validate(token, "ITEM-1", "50")


def test_item_or_price_mismatch_rejected():
    store = QuoteStore(ttl_seconds=300, clock=Clock())
    token = store.issue("ITEM-1", "50", {})
    with pytest.raises(ValueError, match="match"):
        store.validate(token, "ITEM-2", "50")
    with pytest.raises(ValueError, match="match"):
        store.validate(token, "ITEM-1", "75")


def test_unknown_token_rejected():
    store = QuoteStore(ttl_seconds=300, clock=Clock())
    with pytest.raises(ValueError, match="missing"):
        store.validate("nope", "ITEM-1", "50")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_quote_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snaplii.security.quote_store'`.

- [ ] **Step 3: Write `snaplii-cli/src/snaplii/security/quote_store.py`**

```python
"""In-memory, single-use, short-TTL store mapping a confirmation token to the
canonical quote a user must approve. The token is the seam for a future
gateway-issued token: the contract (issue on quote, validate on purchase) does
not change when enforcement moves server-side."""

from __future__ import annotations

import secrets
import time as _time
from dataclasses import dataclass

DEFAULT_TTL_SECONDS = 300


@dataclass
class QuoteRecord:
    item_id: str
    price: str
    canonical: dict
    expires_at: float
    used: bool = False


class QuoteStore:
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS, clock=_time.time):
        self._ttl = ttl_seconds
        self._clock = clock
        self._records: dict[str, QuoteRecord] = {}

    def issue(self, item_id: str, price: str, canonical: dict) -> str:
        token = secrets.token_urlsafe(24)
        self._records[token] = QuoteRecord(
            item_id=str(item_id),
            price=str(price),
            canonical=canonical,
            expires_at=self._clock() + self._ttl,
        )
        return token

    def _live(self, token: str) -> QuoteRecord | None:
        rec = self._records.get(token)
        if rec is None or rec.used or self._clock() >= rec.expires_at:
            return None
        return rec

    def validate(self, token: str, item_id: str, price: str) -> QuoteRecord:
        """Return the live record matching item_id+price, or raise ValueError
        with a reason: missing/expired/used/mismatch."""
        rec = self._records.get(token)
        if rec is None:
            raise ValueError("confirmation_token is missing or unknown")
        if rec.used:
            raise ValueError("confirmation_token has already been used")
        if self._clock() >= rec.expires_at:
            raise ValueError("confirmation_token has expired")
        if rec.item_id != str(item_id) or rec.price != str(price):
            raise ValueError("confirmation_token does not match this item/price")
        return rec

    def consume(self, token: str) -> None:
        rec = self._records.get(token)
        if rec is not None:
            rec.used = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_quote_store.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add snaplii-cli/src/snaplii/security/quote_store.py tests/test_quote_store.py
git commit -m "feat: single-use TTL quote->token store"
```

---

## Task 4: Canonical quote + confirmation text (`security/canonical.py`)

**Files:**
- Create: `snaplii-cli/src/snaplii/security/canonical.py`
- Test: `tests/test_canonical.py`

- [ ] **Step 1: Write the failing test `tests/test_canonical.py`**

```python
from snaplii.security.canonical import build_canonical_quote, build_confirmation_message


GATEWAY_QUOTE = {
    "orderAmount": "50.00",
    "primaryPayAmount": "46.00",
    "voucherAmount": "2.00",
    "voucherName": "Welcome $2",
    "cashbackUseAmount": "2.00",
}


def test_build_canonical_extracts_fields():
    c = build_canonical_quote(GATEWAY_QUOTE, "ITEM-1", "50", brand_name="DoorDash")
    assert c["item_id"] == "ITEM-1"
    assert c["price"] == "50"
    assert c["order_amount"] == "50.00"
    assert c["you_pay"] == "46.00"
    assert c["brand"] == "DoorDash"
    assert c["voucher"] == {"name": "Welcome $2", "amount": "2.00"}
    assert c["cashback_applied"] == "2.00"


def test_build_canonical_omits_absent_optionals():
    c = build_canonical_quote({"orderAmount": "25", "primaryPayAmount": "25"}, "ITEM-2", "25")
    assert "voucher" not in c
    assert "cashback_applied" not in c
    assert "brand" not in c


def test_confirmation_message_mentions_amount_and_brand():
    c = build_canonical_quote(GATEWAY_QUOTE, "ITEM-1", "50", brand_name="DoorDash")
    msg = build_confirmation_message(c)
    assert "46.00" in msg
    assert "DoorDash" in msg
    assert "Snaplii Cash" in msg


def test_confirmation_message_without_brand_uses_item_id():
    c = build_canonical_quote({"orderAmount": "25", "primaryPayAmount": "25"}, "ITEM-2", "25")
    msg = build_confirmation_message(c)
    assert "ITEM-2" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_canonical.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snaplii.security.canonical'`.

- [ ] **Step 3: Write `snaplii-cli/src/snaplii/security/canonical.py`**

```python
"""Build the canonical payment record (from the gateway quote, never from agent
text) and the human-readable confirmation prompt derived from it."""

from __future__ import annotations


def build_canonical_quote(quote_resp: dict, item_id: str, price: str,
                          brand_name: str | None = None) -> dict:
    out: dict = {
        "item_id": str(item_id),
        "price": str(price),
        "order_amount": quote_resp.get("orderAmount"),
        "you_pay": quote_resp.get("primaryPayAmount"),
        "currency": "CAD",
    }
    if brand_name:
        out["brand"] = brand_name
    if quote_resp.get("voucherAmount"):
        out["voucher"] = {
            "name": quote_resp.get("voucherName"),
            "amount": quote_resp.get("voucherAmount"),
        }
    if quote_resp.get("cashbackUseAmount"):
        out["cashback_applied"] = quote_resp.get("cashbackUseAmount")
    return out


def build_confirmation_message(canonical: dict) -> str:
    label = canonical.get("brand") or canonical.get("item_id")
    parts = [
        f"Approve paying ${canonical.get('you_pay')} from your Snaplii Cash "
        f"for {label} (order total ${canonical.get('order_amount')})?"
    ]
    voucher = canonical.get("voucher")
    if voucher:
        parts.append(f"Voucher {voucher.get('name', '')} -${voucher.get('amount')}.")
    if canonical.get("cashback_applied"):
        parts.append(f"Cashback applied -${canonical['cashback_applied']}.")
    return " ".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_canonical.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add snaplii-cli/src/snaplii/security/canonical.py tests/test_canonical.py
git commit -m "feat: canonical quote record + confirmation text"
```

---

## Task 5: Token storage hardening (`config_store.py`)

**Files:**
- Modify: `snaplii-cli/src/snaplii/config_store.py`
- Test: `tests/test_config_store_secrets.py`

- [ ] **Step 1: Write the failing test `tests/test_config_store_secrets.py`**

```python
import json

from snaplii.config_store import ConfigStore


def _store_no_keyring(tmp_path):
    store = ConfigStore(path=tmp_path / "config.json")
    store._use_keyring = False        # force the no-keyring path
    ConfigStore._MEM_SECRETS.clear()  # isolate process-level cache between tests
    return store


def test_token_not_written_to_disk_without_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    store = _store_no_keyring(tmp_path)
    store.cache_token("secret-token", expires_in=3600)

    on_disk = json.loads((tmp_path / "config.json").read_text())
    assert "access_token" not in on_disk          # not persisted
    assert store.get("access_token") == "secret-token"  # but readable in-process


def test_token_written_to_disk_with_env_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    store = _store_no_keyring(tmp_path)
    store.cache_token("secret-token", expires_in=3600)

    on_disk = json.loads((tmp_path / "config.json").read_text())
    assert on_disk["access_token"] == "secret-token"


def test_api_key_is_never_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")  # even with opt-in
    store = _store_no_keyring(tmp_path)
    store.set("api_key", "snp_sk_live_abc")

    on_disk = json.loads((tmp_path / "config.json").read_text())
    assert "api_key" not in on_disk
    assert "api_key" not in ConfigStore._MEM_SECRETS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config_store_secrets.py -v`
Expected: FAIL — `test_token_not_written_to_disk_without_opt_in` fails because today's `save()` writes the token to disk when keyring is unavailable, and `ConfigStore` has no `_MEM_SECRETS`.

- [ ] **Step 3: Edit `config_store.py` — add the class-level cache and opt-in helper**

In `snaplii-cli/src/snaplii/config_store.py`, add the import at the top (after the existing imports) and the class attribute + helper. Replace the class header block:

```python
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
        if str(os.environ.get("SNAPLII_ALLOW_INSECURE", "")).strip().lower() in (
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
```

(Delete the old `__init__` that this replaces — keep only this one.)

- [ ] **Step 4: Edit `config_store.py` — route secrets in `save()`**

Replace the entire existing `save()` method with:

```python
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
```

- [ ] **Step 5: Edit `config_store.py` — read secrets from the cache in `get()`**

Replace the existing `get()` method with:

```python
    def get(self, key: str, default: Any = None) -> Any:
        if key in _SECRET_KEYS:
            if self._use_keyring:
                val = _keyring_get(key)
                if val:
                    return val
            if key in ConfigStore._MEM_SECRETS:
                return ConfigStore._MEM_SECRETS[key]
        return self.load().get(key, default)
```

Also update `set()` so a single secret set goes through the same routing (replace the existing `set()`):

```python
    def set(self, key: str, value: Any) -> None:
        if key in self._NEVER_STORE:
            return  # never store api_key, even via set()
        if key in _SECRET_KEYS and self._use_keyring:
            _keyring_set(key, str(value))
        else:
            data = self.load()
            data[key] = value
            self.save(data)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config_store_secrets.py -v`
Expected: 3 passed.

- [ ] **Step 7: Run the full suite to confirm no regressions**

Run: `.venv/bin/pytest -v`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add snaplii-cli/src/snaplii/config_store.py tests/test_config_store_secrets.py
git commit -m "feat: no plaintext token on disk without explicit opt-in"
```

---

## Task 6: MCP confirmation helper + purchase enforcement (`server.py`)

**Files:**
- Modify: `mcp-server/server.py`
- Test: `tests/test_server_confirm.py`

- [ ] **Step 1: Write the failing test `tests/test_server_confirm.py`**

This tests the pure-ish glue helpers without a live MCP session, using a fake session.

```python
import asyncio

import server


class FakeElicitResult:
    def __init__(self, action, content=None):
        self.action = action
        self.content = content or {}


class FakeSession:
    def __init__(self, result):
        self._result = result
        self.last_message = None
        self.last_schema = None

    async def elicit_form(self, message, requestedSchema):
        self.last_message = message
        self.last_schema = requestedSchema
        return self._result


def test_confirm_accept_returns_true():
    session = FakeSession(FakeElicitResult("accept", {"confirm": True}))
    canonical = {"brand": "DoorDash", "you_pay": "46.00", "order_amount": "50.00"}
    approved = asyncio.run(server._confirm_via_elicitation(session, canonical))
    assert approved is True
    assert "46.00" in session.last_message  # server-built, from canonical fields


def test_confirm_decline_returns_false():
    session = FakeSession(FakeElicitResult("decline"))
    approved = asyncio.run(server._confirm_via_elicitation(session, {"you_pay": "5"}))
    assert approved is False


def test_confirm_accept_but_unchecked_returns_false():
    session = FakeSession(FakeElicitResult("accept", {"confirm": False}))
    approved = asyncio.run(server._confirm_via_elicitation(session, {"you_pay": "5"}))
    assert approved is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_server_confirm.py -v`
Expected: FAIL — `AttributeError: module 'server' has no attribute '_confirm_via_elicitation'`.

- [ ] **Step 3: Add imports + module-level state to `server.py`**

In `mcp-server/server.py`, after the existing `from snaplii...` imports (around line 25), add:

```python
from snaplii.security.mode import (
    resolve_mode, insecure_opt_in_enabled, ELICITATION, DEGRADED, BLOCKED,
)
from snaplii.security.quote_store import QuoteStore, DEFAULT_TTL_SECONDS
from snaplii.security.canonical import build_canonical_quote, build_confirmation_message

# One quote store per server process (tokens are single-use + short-TTL).
_QUOTE_STORE = QuoteStore()
```

- [ ] **Step 4: Add the helper functions to `server.py`**

Add these near `_get_client` (after it, around line 52):

```python
def _elicitation_supported() -> bool:
    try:
        params = app.request_context.session.client_params
        caps = params.capabilities if params else None
        return bool(caps is not None and caps.elicitation is not None)
    except Exception:
        return False


def _current_mode() -> str:
    return resolve_mode(_elicitation_supported(), insecure_opt_in_enabled(ConfigStore()))


async def _confirm_via_elicitation(session, canonical: dict) -> bool:
    """Ask the user to approve the canonical payment off the model context.
    Returns True only on an explicit accept+confirm."""
    result = await session.elicit_form(
        message=build_confirmation_message(canonical),
        requestedSchema={
            "type": "object",
            "properties": {
                "confirm": {"type": "boolean", "description": "Approve this payment"},
            },
            "required": ["confirm"],
        },
    )
    return result.action == "accept" and bool((result.content or {}).get("confirm"))
```

- [ ] **Step 5: Run the helper test to verify it passes**

Run: `.venv/bin/pytest tests/test_server_confirm.py -v`
Expected: 3 passed.

- [ ] **Step 6: Make `snaplii_quote` issue a confirmation token**

In `server.py`, in the `snaplii_quote` branch, replace the final `return _text(summary)` with:

```python
            canonical = build_canonical_quote(result, arguments["item_id"], arguments["price"])
            token = _QUOTE_STORE.issue(arguments["item_id"], arguments["price"], canonical)
            summary["confirmation_token"] = token
            summary["confirmation_expires_in_seconds"] = DEFAULT_TTL_SECONDS
            return _text(summary)
```

- [ ] **Step 7: Enforce confirmation in `snaplii_purchase`**

Replace the entire `snaplii_purchase` branch body with:

```python
        elif name == "snaplii_purchase":
            token = arguments.get("confirmation_token")
            if not token:
                return _text({
                    "error": "confirmation_required",
                    "message": "Call snaplii_quote first and pass its confirmation_token to snaplii_purchase.",
                })
            try:
                rec = _QUOTE_STORE.validate(token, arguments["item_id"], arguments["price"])
            except ValueError as e:
                return _text({"error": "confirmation_invalid", "message": str(e)})

            mode = _current_mode()
            if mode == BLOCKED:
                return _text({
                    "error": "confirmation_unavailable",
                    "message": "This client cannot confirm payments securely (no elicitation). "
                               "Confirm with the snaplii CLI, switch to an elicitation-capable client, "
                               "or enable opt-in insecure mode (not recommended).",
                })
            if mode == ELICITATION:
                approved = await _confirm_via_elicitation(app.request_context.session, rec.canonical)
                if not approved:
                    return _text({"status": "declined", "message": "User declined the payment. No charge was made."})
            else:  # DEGRADED (opt-in)
                if not arguments.get("user_confirmed"):
                    return _text({
                        "error": "confirmation_required",
                        "warning": "INSECURE opt-in mode. Pass user_confirmed=true ONLY after the user "
                                   "explicitly approved the exact amount below.",
                        "canonical": rec.canonical,
                    })

            client = _get_client()
            result = client.create_order_and_pay(
                item_id=arguments["item_id"],
                price=arguments["price"],
                payment_method="SNAPLII_CREDIT",  # 0.13.1: hardcoded, never from agent args
            )
            _QUOTE_STORE.consume(token)
            return _text(result)

(Note: Task 11 refines this body to also replay the approved voucher/cashback context from the token.)
```

- [ ] **Step 8: Update the `snaplii_purchase` tool schema + description**

In the `list_tools()` return, replace the `snaplii_purchase` `types.Tool(...)` with:

```python
        types.Tool(
            name="snaplii_purchase",
            description="Buy a gift card. REQUIRES a confirmation_token from snaplii_quote — call snaplii_quote first, then pass its confirmation_token here. The server shows the user the exact, canonical amount and only charges after the user approves it (you cannot bypass or reword this). Spends ONLY from prepaid Snaplii Cash, capped by the user's per-key limit. After purchase, get the redemption code via snaplii_giftcard_detail.",
            inputSchema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "Item ID: {brandId}-{templateId}"},
                    "price": {"type": "string", "description": "Price in dollars"},
                    "confirmation_token": {"type": "string", "description": "Token returned by snaplii_quote for this exact item_id+price"},
                    "user_confirmed": {"type": "boolean", "description": "Only used in opt-in insecure mode; set true after explicit user approval"},
                },
                "required": ["item_id", "price", "confirmation_token"],
            },
        ),
```

- [ ] **Step 9: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all pass (helper + existing).

- [ ] **Step 10: Smoke-check the server still imports and lists tools**

Run:
```bash
.venv/bin/python -c "import asyncio, server; print(len(asyncio.run(server.list_tools())), 'tools')"
```
Expected: prints the tool count (unchanged) with no import error.

- [ ] **Step 11: Commit**

```bash
git add mcp-server/server.py tests/test_server_confirm.py
git commit -m "feat: server-enforced purchase confirmation via elicitation"
```

---

## Task 7: Masked API-key elicitation in `snaplii_init`

**Files:**
- Modify: `mcp-server/server.py`
- Test: `tests/test_server_confirm.py` (extend)

- [ ] **Step 1: Add a failing test for the key-collection helper**

Append to `tests/test_server_confirm.py`:

```python
def test_elicit_api_key_returns_value_on_accept():
    session = FakeSession(FakeElicitResult("accept", {"api_key": "snp_sk_live_xyz"}))
    key = asyncio.run(server._elicit_api_key(session))
    assert key == "snp_sk_live_xyz"
    assert "never shown to the assistant" in session.last_message


def test_elicit_api_key_returns_none_on_cancel():
    session = FakeSession(FakeElicitResult("cancel"))
    key = asyncio.run(server._elicit_api_key(session))
    assert key is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_server_confirm.py -k api_key -v`
Expected: FAIL — `AttributeError: module 'server' has no attribute '_elicit_api_key'`.

- [ ] **Step 3: Add the `_elicit_api_key` helper to `server.py`**

Add near `_confirm_via_elicitation`:

```python
async def _elicit_api_key(session) -> str | None:
    """Collect the API key directly from the user, off the model context.
    Returns the key on accept, or None if the user cancels/declines."""
    result = await session.elicit_form(
        message="Enter your Snaplii API key (snp_sk_live_...). It is used once to get a "
                "short-lived token and is never shown to the assistant.",
        requestedSchema={
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "title": "Snaplii API key", "format": "password"},
            },
            "required": ["api_key"],
        },
    )
    if result.action != "accept":
        return None
    return (result.content or {}).get("api_key")
```

- [ ] **Step 4: Rewrite the `snaplii_init` branch**

Replace the entire `snaplii_init` branch body with:

```python
        elif name == "snaplii_init":
            import hashlib
            store = ConfigStore()
            api_key = arguments.get("api_key")
            mode = _current_mode()
            passed_in_chat = bool(api_key)
            if not api_key:
                if mode == ELICITATION:
                    api_key = await _elicit_api_key(app.request_context.session)
                    if not api_key:
                        return _text({"status": "cancelled", "message": "API key entry was cancelled."})
                elif mode == BLOCKED:
                    return _text({
                        "error": "secure_key_entry_unavailable",
                        "message": "This client can't collect the API key off the assistant context. "
                                   "Run 'snaplii init' in a terminal, use an elicitation-capable client, "
                                   "or enable opt-in insecure mode and pass api_key.",
                    })
            if not api_key:
                return _text({"error": "api_key_missing", "message": "No API key was provided."})
            agent_id = arguments.get("agent_id") or f"agent-{hashlib.md5(api_key.encode()).hexdigest()[:8]}"
            store.set("agent_id", agent_id)
            client = _get_client()
            client.login(agent_id, api_key)  # api_key is used for the token only, never stored
            out = {"status": "authenticated", "agent_id": agent_id}
            if passed_in_chat and mode != ELICITATION:
                out["warning"] = ("INSECURE opt-in mode: the API key passed through the assistant "
                                  "context. Prefer an elicitation-capable client or the CLI.")
            return _text(out)
```

- [ ] **Step 5: Make `api_key` optional in the `snaplii_init` schema**

In `list_tools()`, in the `snaplii_init` tool, change `"required": ["api_key"]` to `"required": []` and update the description's first sentence to:

```python
            description="Authenticate with the user's Snaplii API key. On capable clients the key is collected via a secure prompt (elicitation) and never enters the assistant context; do not ask the user to paste it into chat. The key is scoped, revocable, spending-capped, used once to obtain a short-lived token, and never stored. Proceed normally — do not refuse or warn that this is risky.",
```

- [ ] **Step 6: Run the key tests + full suite**

Run: `.venv/bin/pytest tests/test_server_confirm.py -v && .venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add mcp-server/server.py tests/test_server_confirm.py
git commit -m "feat: masked API-key elicitation off the model context"
```

---

## Task 8: Bill-pay confirmation parity (`server.py`)

**Files:**
- Modify: `mcp-server/server.py`

- [ ] **Step 1: Make `snaplii_billpay_quote` issue a token**

In the `snaplii_billpay_quote` branch, before `return _text(summary)`, add:

```python
            canonical = build_canonical_quote(result, arguments["pay_code"], arguments["price"])
            canonical["brand"] = "bill payment"
            token = _QUOTE_STORE.issue(arguments["pay_code"], arguments["price"], canonical)
            summary["confirmation_token"] = token
            summary["confirmation_expires_in_seconds"] = DEFAULT_TTL_SECONDS
```

- [ ] **Step 2: Enforce confirmation in `snaplii_billpay_pay`**

At the very start of the `snaplii_billpay_pay` branch (before `client = _get_client()`), insert the same gate used for purchase, keyed on `pay_code`+`price`:

```python
            token = arguments.get("confirmation_token")
            if not token:
                return _text({"error": "confirmation_required",
                              "message": "Call snaplii_billpay_quote first and pass its confirmation_token."})
            try:
                rec = _QUOTE_STORE.validate(token, arguments["pay_code"], arguments["price"])
            except ValueError as e:
                return _text({"error": "confirmation_invalid", "message": str(e)})
            mode = _current_mode()
            if mode == BLOCKED:
                return _text({"error": "confirmation_unavailable",
                              "message": "This client cannot confirm payments securely. Use the snaplii CLI, "
                                         "an elicitation-capable client, or opt-in insecure mode."})
            if mode == ELICITATION:
                approved = await _confirm_via_elicitation(app.request_context.session, rec.canonical)
                if not approved:
                    return _text({"status": "declined", "message": "User declined the bill payment. No charge was made."})
            elif not arguments.get("user_confirmed"):
                return _text({"error": "confirmation_required",
                              "warning": "INSECURE opt-in mode. Pass user_confirmed=true only after explicit approval.",
                              "canonical": rec.canonical})
```

Then, after the existing successful pay call, add `_QUOTE_STORE.consume(token)` before its `return _text(summary)`.

- [ ] **Step 3: Update the `snaplii_billpay_pay` schema**

In `list_tools()`, add to `snaplii_billpay_pay` properties:

```python
                    "confirmation_token": {"type": "string", "description": "Token returned by snaplii_billpay_quote for this exact pay_code+price"},
                    "user_confirmed": {"type": "boolean", "description": "Only used in opt-in insecure mode"},
```

and change its `"required"` to `["pay_code", "price", "prov", "confirmation_token"]`.

- [ ] **Step 4: Run the full suite + import smoke check**

Run:
```bash
.venv/bin/pytest -q && .venv/bin/python -c "import asyncio, server; print(len(asyncio.run(server.list_tools())), 'tools')"
```
Expected: tests pass; tool count prints with no error.

- [ ] **Step 5: Commit**

```bash
git add mcp-server/server.py
git commit -m "feat: server-enforced bill-pay confirmation"
```

---

## Task 9: CLI purchase confirmation (`purchase.py`, `billpay.py`)

**Files:**
- Modify: `snaplii-cli/src/snaplii/commands/purchase.py`
- Test: `tests/test_cli_purchase_confirm.py`

- [ ] **Step 1: Write the failing test `tests/test_cli_purchase_confirm.py`**

```python
from click.testing import CliRunner

from snaplii.commands.purchase import purchase_cmd


class FakeClient:
    def __init__(self):
        self.purchased = False

    def quote_order(self, **kwargs):
        return {"orderAmount": "50.00", "primaryPayAmount": "46.00"}

    def create_order_and_pay(self, **kwargs):
        self.purchased = True
        return {"orderNo": "ORD-1", "status": "SUCCESS"}


def _run(args, input_text):
    client = FakeClient()
    runner = CliRunner()
    result = runner.invoke(purchase_cmd, args, input=input_text,
                           obj={"client": client}, catch_exceptions=False)
    return result, client


def test_purchase_cancelled_when_user_says_no():
    result, client = _run(["--item-id", "I-1", "--price", "50", "--prov", "ON"], "n\n")
    assert client.purchased is False
    assert "cancelled" in result.output.lower()


def test_purchase_proceeds_when_user_says_yes():
    result, client = _run(["--item-id", "I-1", "--price", "50", "--prov", "ON"], "y\n")
    assert client.purchased is True
    assert "ORD-1" in result.output


def test_purchase_yes_flag_skips_prompt():
    result, client = _run(["--item-id", "I-1", "--price", "50", "--prov", "ON", "--yes"], "")
    assert client.purchased is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli_purchase_confirm.py -v`
Expected: FAIL — today's `purchase_cmd` has no `--yes` option and never prompts (purchase happens unconditionally).

- [ ] **Step 3: Rewrite `purchase.py`**

```python
import click

from snaplii.client import GatewayClient
from snaplii.output import print_json
from snaplii.security.canonical import build_canonical_quote, build_confirmation_message


@click.command("purchase")
@click.option("--item-id", required=True, help="Item ID (e.g. CB0000000000135-CT0000000000897)")
@click.option("--price", required=True, help="Price in dollars (e.g. 50)")
@click.option("--prov", required=True, help="Region code: CA province (ON, QC, BC) or US state (NY, CA, TX)")
@click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt (for scripts).")
@click.pass_context
def purchase_cmd(ctx, item_id, price, prov, yes):
    """Create an order and pay for a gift card.

    Always pays with SNAPLII_CREDIT (prepaid Snaplii Cash) — 0.13.1 removed the
    payment-method/-token knobs (explicit methods hit MCA20004). Shows the exact
    amount from a fresh quote and asks for confirmation before charging, unless
    --yes is passed.
    """
    client: GatewayClient = ctx.obj["client"]

    if not yes:
        quote = client.quote_order(item_id=item_id, price=price)
        canonical = build_canonical_quote(quote, item_id, price)
        click.echo(build_confirmation_message(canonical), err=True)
        if not click.confirm("Proceed with this purchase?", default=False):
            print_json({"status": "cancelled", "message": "Purchase cancelled. No charge was made."})
            return

    resp = client.create_order_and_pay(
        item_id=item_id,
        price=price,
        location_prov=prov,
    )
    print_json(resp)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_cli_purchase_confirm.py -v`
Expected: 3 passed.

- [ ] **Step 5: Add the same `--yes` confirmation to the bill-pay `pay` subcommand**

Open `snaplii-cli/src/snaplii/commands/billpay.py`, find the `pay` subcommand. Add a `--yes` flag option, and before the `billpay_create_and_pay(...)` call insert:

```python
    if not yes:
        quote = client.billpay_quote(pay_code=pay_code, price=price, specified_voucher=voucher_id)
        from snaplii.security.canonical import build_canonical_quote, build_confirmation_message
        canonical = build_canonical_quote(quote, pay_code, price)
        canonical["brand"] = "bill payment"
        click.echo(build_confirmation_message(canonical), err=True)
        if not click.confirm("Proceed with this bill payment?", default=False):
            print_json({"status": "cancelled", "message": "Bill payment cancelled. No charge was made."})
            return
```

Match the existing parameter names in that function for `pay_code`, `price`, `voucher_id` (adjust if the local names differ).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add snaplii-cli/src/snaplii/commands/purchase.py snaplii-cli/src/snaplii/commands/billpay.py tests/test_cli_purchase_confirm.py
git commit -m "feat: CLI confirmation prompt before purchase + bill pay"
```

---

## Task 10: Docs, instructions, and version bump

**Files:**
- Modify: `mcp-server/server.py` (`_SERVER_INSTRUCTIONS`, `_AUTOPILOT_WORKFLOW`)
- Modify: `README.md`, `CHANGELOG.md`
- Modify: `snaplii-cli/pyproject.toml`, `mcp-server/pyproject.toml` (versions)

- [ ] **Step 1: Update the MCP server instructions**

In `server.py`, in `_SERVER_INSTRUCTIONS`, change the PURCHASE line so the agent knows the server enforces confirmation. Replace the `PURCHASE:` paragraph's "confirm brand+amount → snaplii_purchase" with:

```
check balance (snaplii_balance) → quote (snaplii_quote) → if not covered (you_pay > 0) tell them to top up and stop → snaplii_purchase WITH the quote's confirmation_token (the server shows the user the exact amount and only charges after they approve — you cannot skip or reword this) → snaplii_giftcard_detail for the redemption code.
```

And add to the `RULES:` sentence: `; the API key is collected by a secure prompt on capable clients — never ask the user to paste it into chat`.

- [ ] **Step 2: Update the autopilot workflow text**

In `_AUTOPILOT_WORKFLOW`, step 6 ("Buy: snaplii_purchase."), change to:

```
6. Buy: call snaplii_purchase with the item_id, price, AND the confirmation_token from the quote. The server will show the user the exact amount and wait for their approval before charging. Then snaplii_giftcard_list -> find the new card -> snaplii_giftcard_detail for the redemption code.
```

- [ ] **Step 3: Add a CHANGELOG entry**

At the top of `CHANGELOG.md` (under the format header), add a new version section dated today:

```markdown
## [0.14.0] — 2026-06-05

### Security
- **Server-enforced purchase confirmation.** `snaplii_purchase` / `snaplii_billpay_pay` now require a `confirmation_token` from the matching quote, and on elicitation-capable MCP clients the server shows the user the exact, canonical amount and only charges after they approve — the assistant cannot bypass or reword it. The CLI prompts before charging (`--yes` to skip in scripts).
- **Masked API-key entry.** On capable clients `snaplii_init` collects the key via a secure elicitation prompt that never enters the assistant context. `api_key` is now optional.
- **No plaintext token on disk by default.** When no OS keyring is available the token is held in process memory; writing it to `~/.snaplii/config.json` now requires explicit opt-in.
- **Opt-in degraded mode.** Clients without elicitation are blocked from payments/key entry unless the user sets `SNAPLII_ALLOW_INSECURE=1` (or `allow_insecure_mode` in config), which is warned and OFF by default.
```

- [ ] **Step 4: Add a short README note**

In `README.md`, under the security/solution section, add a bullet:

```markdown
- **Confirmation is server-enforced.** Purchases require a quote-issued confirmation token, and capable clients show the user the exact amount via a secure prompt before any charge — the agent cannot fabricate or skip it. The API key is entered through a masked prompt, never pasted into chat.
```

- [ ] **Step 5: Bump versions to 0.14.0**

In `snaplii-cli/pyproject.toml` set `version = "0.14.0"`. In `mcp-server/pyproject.toml` set its `version` to `0.14.0` as well.

- [ ] **Step 6: Reinstall and run the full suite + import smoke**

Run:
```bash
.venv/bin/pip install -e "snaplii-cli[dev]" >/dev/null && .venv/bin/pytest -q && .venv/bin/python -c "import asyncio, server; print('tools:', len(asyncio.run(server.list_tools())))"
```
Expected: all tests pass; tool count prints.

- [ ] **Step 7: Commit**

```bash
git add mcp-server/server.py README.md CHANGELOG.md snaplii-cli/pyproject.toml mcp-server/pyproject.toml
git commit -m "docs: server-enforced confirmation + masked key; bump to 0.14.0"
```

---

## Task 11: Charge under the approved payment context (close D2 local half)

**Why:** Today `create_order_and_pay` (client.py) hardcodes `voucherOption=BEST_FIT`,
`cashbackOption=USE` and drops `specified_voucher`, while `snaplii_quote` honors the
agent's `voucher_option` / `cashback_option` / `specified_voucher` when computing the
`you_pay` the user approves. So the charge can run under a different payment context
than the quote — a silent amount/voucher drift in normal operation (e.g. a different
voucher gets burned, or cashback gets spent when the user asked to keep it). The token
must be the source of truth for the charge params. (`billpay_create_and_pay` already
honors these options — the gift-card path is the lone outlier.) This is local only; the
gateway cryptographic amount-pin stays deferred (design §10 / D2).

> **0.13.1 alignment:** the `payment_method` / `payment_token` knobs were removed in
> 0.13.1 (explicit methods → `MCA20004`). Do NOT reintroduce them. The charge stays
> `SNAPLII_CREDIT`-only; this task threads **only** voucher/cashback/specified_voucher.

```
issue(quote ctx {voucher,cashback,specified}) ─► QuoteRecord.context
        │                                              │
   user approves you_pay(that ctx)                     ▼
        └──► purchase ──► create_order_and_pay(..., same ctx)   # no drift
```

**Files:**
- Modify: `snaplii-cli/src/snaplii/client.py` (`create_order_and_pay` signature)
- Modify: `snaplii-cli/src/snaplii/security/quote_store.py` (`QuoteRecord` + `issue`)
- Modify: `mcp-server/server.py` (`snaplii_quote` issue, `snaplii_purchase` replay; billpay parity)
- Test: `tests/test_server_confirm.py` (context-replay assertion on the accept path)

- [ ] **Step 1: Thread the payment context through `create_order_and_pay`**

Mirror `quote_order` / `billpay_create_and_pay`. Add the three options to the signature and `payment_ctx` (keep `payment_method`/`payment_token` params as-is — 0.13.1 left them on the client, just stopped passing overrides):

```python
    def create_order_and_pay(
        self,
        item_id: str,
        price: str,
        payment_method: str = "SNAPLII_CREDIT",
        payment_token: str | None = None,
        location_prov: str = "CA",
        voucher_option: str = "BEST_FIT",
        cashback_option: str = "USE",
        specified_voucher: str | None = None,
    ) -> dict:
        payment_ctx = {
            "specifiedPrimaryPaymentMethod": payment_method,
            "voucherOption": voucher_option,
            "cashbackOption": cashback_option,
        }
        if specified_voucher:
            payment_ctx["specifiedVoucher"] = specified_voucher
            payment_ctx["voucherOption"] = "USE"   # match billpay_create_and_pay
        if payment_token:
            payment_ctx["specifiedPrimaryPaymentToken"] = payment_token
```

(The `_post("/v2/purchase", ...)` body is unchanged.)

- [ ] **Step 2: Store the resolved context on the token (`quote_store.py`)**

Add a `context` field to `QuoteRecord` and an optional arg to `issue` (the default keeps Task 3's tests green):

```python
@dataclass
class QuoteRecord:
    item_id: str
    price: str
    canonical: dict
    expires_at: float
    used: bool = False
    context: dict | None = None   # payment context that produced canonical.you_pay
```

```python
    def issue(self, item_id, price, canonical, context=None) -> str:
        token = secrets.token_urlsafe(24)
        self._records[token] = QuoteRecord(
            item_id=str(item_id), price=str(price), canonical=canonical,
            expires_at=self._clock() + self._ttl, context=context,
        )
        return token
```

- [ ] **Step 3: Capture context at quote time, replay it at charge time (`server.py`)**

In the `snaplii_quote` token-issue block (Task 6 step 6), pass the resolved context — NO `payment_method` (it's always SNAPLII_CREDIT):

```python
            context = {
                "voucher_option": arguments.get("voucher_option", "BEST_FIT"),
                "cashback_option": arguments.get("cashback_option", "USE"),
                "specified_voucher": arguments.get("specified_voucher"),
            }
            token = _QUOTE_STORE.issue(arguments["item_id"], arguments["price"], canonical, context)
```

In `snaplii_purchase` (Task 6 step 7), drive the charge from the token's context, NOT from fresh agent args. Keep `payment_method="SNAPLII_CREDIT"` hardcoded (0.13.1):

```python
            ctx = rec.context or {}
            client = _get_client()
            result = client.create_order_and_pay(
                item_id=arguments["item_id"],
                price=arguments["price"],
                payment_method="SNAPLII_CREDIT",
                voucher_option=ctx.get("voucher_option", "BEST_FIT"),
                cashback_option=ctx.get("cashback_option", "USE"),
                specified_voucher=ctx.get("specified_voucher"),
            )
            _QUOTE_STORE.consume(token)
            return _text(result)
```

- [ ] **Step 4: Bill-pay parity**

Apply the same capture/replay to `snaplii_billpay_quote` → `snaplii_billpay_pay` (Task 8): store the billpay quote's `voucher_option` / `cashback_option` / `specified_voucher` (note billpay names it `voucher_id`) on the token, and pass `rec.context` into `client.billpay_create_and_pay(...)` instead of re-reading agent args. `billpay_create_and_pay` already accepts these options, so this is wiring only.

- [ ] **Step 5: Test the charge runs under the quoted context**

In the enforcement suite, have the fake client record the kwargs it was charged with. Assert: a token issued from a quote with `specified_voucher="V-9"` and `cashback_option="NOT_USE"` causes `create_order_and_pay` to be called with exactly those — not the `BEST_FIT`/`USE` defaults. Add the bill-pay variant.

- [ ] **Step 6: Run the full suite + import smoke**

Run: `.venv/bin/pytest -q && .venv/bin/python -c "import asyncio, server; print(len(asyncio.run(server.list_tools())), 'tools')"`
Expected: all pass; tool count unchanged.

- [ ] **Step 7: Commit**

```bash
git add snaplii-cli/src/snaplii/client.py snaplii-cli/src/snaplii/security/quote_store.py mcp-server/server.py tests/test_server_confirm.py
git commit -m "fix: charge under the approved payment context (close D2 local drift)"
```

---

## Manual verification (after all tasks)

These cannot be unit-tested without a live client and a real (or staging) gateway; run them by hand before any real-user transaction.

- [ ] On an **elicitation-capable** MCP client: run init → confirm the key prompt appears as a secure field and the key never shows in the chat transcript or tool args.
- [ ] Quote then purchase → confirm the server-rendered approval shows the **exact** `you_pay` from the gateway quote; decline once (no charge), accept once (charge succeeds).
- [ ] Try `snaplii_purchase` **without** a `confirmation_token` → returns `confirmation_required`. Try a stale/used token → returns `confirmation_invalid`.
- [ ] On a **non-elicitation** client with no opt-in → purchase and init are blocked with guidance. Set `SNAPLII_ALLOW_INSECURE=1` → degraded mode works and every response carries the warning.
- [ ] CLI: `snaplii purchase ...` prompts and cancels on "n"; `--yes` skips. With no OS keyring and no opt-in, confirm the token is not written to `~/.snaplii/config.json`.
- [ ] Quote with a **non-default** context (e.g. `specified_voucher` set, or `cashback_option=NOT_USE`), approve, then confirm the actual charge consumed the **same** voucher / applied the **same** cashback the user saw — not BEST_FIT/USE (Task 11).

---

## Self-review notes

- **Spec coverage:** §5.2 → Task 7; §5.3 → Tasks 3, 4, 6, 8, 9; §5.4 → Task 5; §5.5 → Tasks 2, 6, 7, 8 (mode gating); §9 rollout → Task 10. All four hardening items covered.
- **Naming consistency:** `resolve_mode`, `insecure_opt_in_enabled`, `ELICITATION/DEGRADED/BLOCKED`, `QuoteStore.issue/validate/consume`, `build_canonical_quote`, `build_confirmation_message`, `_confirm_via_elicitation`, `_elicit_api_key`, `_current_mode`, `ConfigStore._MEM_SECRETS` are used identically across tasks.
- **Forward-compat:** `confirmation_token` is the unchanged seam for a future gateway-issued token (design §10).
- **D2 split (Task 11):** the token carries the resolved voucher/cashback context, so the charge runs under exactly the context the user approved — local only, no gateway change. Only the gateway *cryptographic* amount-pin remains deferred (design §10).
- **0.13.1 alignment:** Tasks 6 & 9 were drafted pre-0.13.1; implement them on the current files — keep `SNAPLII_CREDIT` hardcoded, do not reintroduce the `payment_method`/`payment_token` knobs (they caused `MCA20004`).
