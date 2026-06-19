"""Lightweight, cached check for a newer release on PyPI.

Runs at most once per day per package, times out fast, and fails silently —
it must never block or break a normal CLI invocation or MCP tool call.
"""
from __future__ import annotations

import json
import time
from importlib.metadata import distribution, version as pkg_version

import httpx

_CHECK_INTERVAL = 86400  # seconds — check PyPI at most once per day


def _parse_version(v: str) -> tuple:
    parts = []
    for chunk in v.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_editable_install(package: str) -> bool:
    """True if the package is a git clone / editable (`pip install -e`) install.
    Such installs can't be updated with `pip install -U` — they update via git pull.
    Detected via PEP 610 direct_url.json."""
    try:
        raw = distribution(package).read_text("direct_url.json")
        if raw:
            info = json.loads(raw)
            return bool(info.get("dir_info", {}).get("editable"))
    except Exception:
        pass
    return False


def update_hint(package: str) -> str:
    """The right upgrade command for how this package was installed."""
    if is_editable_install(package):
        return f"git pull in your {package} checkout (it's an editable/clone install)"
    return f"pip install -U {package}"


def check_for_update(store, package: str = "snaplii-cli",
                     allow_network: bool = True) -> dict | None:
    """Return {'current': ..., 'latest': ...} if a newer version of ``package``
    is on PyPI, else None. Caches the PyPI result in config (one cache key per
    package); queries at most once per day. Never raises.

    allow_network=False makes this a cache-only read — it never makes the (up to
    2s) PyPI request, so it's safe to call on a latency-sensitive path. When the
    cache is empty or stale it simply returns None; refresh the cache separately
    (e.g. from a background thread with allow_network=True)."""
    try:
        current = pkg_version(package)
    except Exception:
        return None

    cache_key = f"_version_check_{package.replace('-', '_')}"
    try:
        now = time.time()
        cache = store.get(cache_key) or {}
        latest = cache.get("latest")
        checked_at = cache.get("checked_at", 0)

        if not latest or now - checked_at >= _CHECK_INTERVAL:
            if not allow_network:
                # Cache-only: don't block on PyPI. Use a stale `latest` if we have
                # one; otherwise we simply can't tell yet.
                if not latest:
                    return None
            else:
                resp = httpx.get(f"https://pypi.org/pypi/{package}/json", timeout=2.0)
                latest = resp.json()["info"]["version"]
                store.set(cache_key, {"latest": latest, "checked_at": now})

        if latest and _parse_version(latest) > _parse_version(current):
            return {"current": current, "latest": latest}
    except Exception:
        return None
    return None
