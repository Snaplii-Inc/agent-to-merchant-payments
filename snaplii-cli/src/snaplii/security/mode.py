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
