"""Lightweight, cached check for a newer release on PyPI.

Runs at most once per day per package, times out fast, and fails silently —
it must never block or break a normal CLI invocation or MCP tool call.
"""
from __future__ import annotations

import time
from importlib.metadata import version as pkg_version

import httpx

_CHECK_INTERVAL = 86400  # seconds — check PyPI at most once per day


def _parse_version(v: str) -> tuple:
    parts = []
    for chunk in v.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check_for_update(store, package: str = "snaplii-cli") -> dict | None:
    """Return {'current': ..., 'latest': ...} if a newer version of ``package``
    is on PyPI, else None. Caches the PyPI result in config (one cache key per
    package); queries at most once per day. Never raises."""
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
            resp = httpx.get(f"https://pypi.org/pypi/{package}/json", timeout=2.0)
            latest = resp.json()["info"]["version"]
            store.set(cache_key, {"latest": latest, "checked_at": now})

        if latest and _parse_version(latest) > _parse_version(current):
            return {"current": current, "latest": latest}
    except Exception:
        return None
    return None
