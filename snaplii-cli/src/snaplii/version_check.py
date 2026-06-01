"""Lightweight, cached check for a newer snaplii-cli release on PyPI.

Runs at most once per day, times out fast, and fails silently — it must never
block or break a normal CLI invocation.
"""
from __future__ import annotations

import time
from importlib.metadata import version as pkg_version

import httpx

_PYPI_URL = "https://pypi.org/pypi/snaplii-cli/json"
_CHECK_INTERVAL = 86400  # seconds — check PyPI at most once per day
_CACHE_KEY = "_version_check"


def _parse_version(v: str) -> tuple:
    parts = []
    for chunk in v.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check_for_update(store) -> dict | None:
    """Return {'current': ..., 'latest': ...} if a newer version is on PyPI,
    else None. Caches the PyPI result in config; queries at most once per day.
    Never raises."""
    try:
        current = pkg_version("snaplii-cli")
    except Exception:
        return None

    try:
        now = time.time()
        cache = store.get(_CACHE_KEY) or {}
        latest = cache.get("latest")
        checked_at = cache.get("checked_at", 0)

        if not latest or now - checked_at >= _CHECK_INTERVAL:
            resp = httpx.get(_PYPI_URL, timeout=2.0)
            latest = resp.json()["info"]["version"]
            store.set(_CACHE_KEY, {"latest": latest, "checked_at": now})

        if latest and _parse_version(latest) > _parse_version(current):
            return {"current": current, "latest": latest}
    except Exception:
        return None
    return None
