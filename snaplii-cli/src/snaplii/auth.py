"""Shared, secret-free authentication policy. No host tools or network calls."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from snaplii.exceptions import ConfigError

DEFAULT_ORIGIN = "https://aipayment.snaplii.com"

MUSE_AUTH_INSTRUCTION = """Use the CLI for Meta Muse, before calling any card-bearing MCP connect tool.
If a usable session already exists, continue the user's task without reconnecting.
Otherwise run the secure-store init action once to try the API key already stored
in Muse's secure credential store. The store holds the API key, not the session.

For credential_required or invalid_key, use only the secure-input invocation
documented below and supplied by a muse_secure_entry action. Invoke it as a native
Muse tool, not Python or shell code; wait for a successful submission before
running after_success. Collect the key through secure input, never through chat.
If no secure-input invocation is supplied, treat secure entry as unavailable.
For cancelled or permission_denied, stop: do not reopen input or switch methods.
For secure_entry_unavailable, explain the limitation and offer the existing login
method only after the user explicitly chooses it. Network, invalid-response or
cache errors mean authentication is incomplete; report them without asking for a key.

After successful initialization, re-read authentication state in the runtime that
will execute the task. Continue only when has_valid_token=true. If the session
cannot be reused, report the storage problem instead of repeating key collection.
Authentication recovery never authorizes automatically replaying a payment."""


def secure_entry_actions() -> dict | None:
    """Native input calls, only when the runtime supplies a verified contract.

    Currently returns None: production actions intentionally offer a fallback
    until T1 verifies the host tool and its request/reconnect schemas.
    """
    actions = {state: build_auth_action(state, host="muse")
               for state in ("credential_required", "invalid_key")}
    if any(action["type"] != "muse_secure_entry" for action in actions.values()):
        return None
    for action in actions.values():
        if (not isinstance(action.get("tool"), str) or not action["tool"]
                or not isinstance(action.get("arguments"), dict)
                or action.get("instruction") != MUSE_AUTH_INSTRUCTION
                or action.get("after_success") != build_auth_action("auth_required", host="muse")):
            raise ValueError("Invalid shared Muse secure-input action contract")
    return actions


def render_auth_skill_block() -> str:
    """Canonical Auth text for each independently distributed Snaplii skill."""
    action = build_auth_action("auth_required", host="muse")
    command = " ".join(action["argv"])
    secure_actions = secure_entry_actions()
    if secure_actions is None:
        invocation = ("Automatic secure-input invocation is unavailable in this version. A missing or\n"
                      "rejected stored key requires the unavailable-path handling above; do not guess a\n"
                      "Muse tool name or its arguments, or claim that a dialog was opened.")
    else:
        invocation = "\n\n".join(
            f"Native Muse tool call for `{state}` (not shell/Python code):\n\n```json\n"
            + json.dumps({"tool": value["tool"], "arguments": value["arguments"]}, indent=2, sort_keys=True)
            + "\n```"
            for state, value in secure_actions.items())
    return f"""## Auth

### When to connect

Installing, updating, or reading this skill alone does not authorize credential
collection or login: do not open credential input, exchange tokens, or probe a
protected endpoint. Report installation separately from connection. A request to
connect, including "install and connect", or to perform a protected Snaplii task
starts the authentication gate below.

### Authentication gate

1. Meta Muse uses the CLI path below. Other agents prefer available Snaplii MCP
   tools; otherwise use the CLI. Check `snaplii config show` for CLI operations or
   `snaplii_config_show` for MCP operations, using the same gateway as the task.
2. Continue to browse, balance, quote, purchase, bill pay, or transfer only when
   `has_valid_token=true` (the JSON boolean). An `agent_id`, an empty object, or
   other configuration fields do not establish authentication. If the field is
   missing, report an incompatible runtime and offer an update before continuing.
3. A valid session needs no `init` or `connect`. Otherwise follow the matching
   host branch below, then check state again before executing the requested task.

### Meta Muse

{MUSE_AUTH_INSTRUCTION}

For the Snaplii production gateway, the secure-store init action is:

```bash
{command}
```

Use this command only for that gateway; for another gateway, stop and explain
that secure credential authentication is unavailable there. `--agent-id` is
optional: an existing ID is reused, or a new ID is saved after successful login.

{invocation}

### Other agents

Keep authentication in the runtime that will use it. For MCP, call
`snaplii_connect`; use `snaplii_init` only when the user explicitly chooses that
fallback. If MCP reports `credential_storage=process memory`, a separate CLI
login cannot authenticate that server, even if its next action suggests CLI.
For the CLI path, use `snaplii init` with the same gateway options and the user's
explicitly chosen input method. Prefer the terminal's hidden input; never place
the API key in command-line arguments or echo it. Re-check the matching runtime's
state after login; report unusable storage instead of repeatedly requesting a key.

### Reauthentication

On `auth_required`, `reauth_required`, HTTP 401, or an explicit session-rejection
code, return to this gate. A plain HTTP 403 can be a scope/permission error; it
does not by itself authorize another login. Honor stop and retry-later actions.
Report cache/configuration errors as such. Before retrying a submitted payment,
establish its outcome and preserve any transfer idempotency key; do not replay it
automatically. Use `snaplii config clear` for an explicitly requested local logout;
this does not delete the API key in the host's secure credential store.
"""


@dataclass(frozen=True)
class MuseEnvironment:
    detected: bool
    reason_code: str


def detect_muse() -> MuseEnvironment:
    # Release gate T1/G1: helper/socket ownership and the host input contract
    # have not been verified in a real Muse runtime. Do not infer trust from
    # client names, environment variables or a user-supplied helper path.
    # Tests inject a detector; there is deliberately no production override.
    return MuseEnvironment(False, "muse_contract_unverified")


def normalize_origin(base_url: str) -> str:
    try:
        if not isinstance(base_url, str) or re.search(r"[\s\\]", base_url):
            raise ValueError
        parts = urlsplit(base_url)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment):
            raise ValueError
        host = parts.hostname.lower()
        port = parts.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        if ":" in host:
            host = "[" + host + "]"
        suffix = "" if port in (None, 443 if parts.scheme == "https" else 80) else f":{port}"
        return f"{parts.scheme}://{host}{suffix}"
    except (ValueError, TypeError):
        raise ConfigError("Invalid gateway URL. Use an HTTP(S) URL without credentials, query or fragment.") from None


def normalize_base_url(base_url: str) -> str:
    """Validate the URL while retaining its gateway routing prefix."""
    origin = normalize_origin(base_url)
    return origin + urlsplit(base_url).path.rstrip("/")


def validate_vault_origin(base_url: str) -> str:
    origin = normalize_origin(base_url)
    if origin != DEFAULT_ORIGIN or urlsplit(base_url).path not in ("", "/"):
        raise ConfigError("Secure credential authentication is allowed only at the Snaplii production HTTPS origin.")
    return origin


def valid_agent_id(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) is not None


def build_auth_action(state: str, *, host: str, auth_method=None, origin=DEFAULT_ORIGIN) -> dict | None:
    if state == "ready":
        return None
    if state in ("cancelled", "permission_denied", "session_cache_failed", "auth_response_invalid"):
        return {"type": "stop", "reason": state}
    if state == "temporary_gateway_error":
        return {"type": "retry_auth_later", "reason": state}
    if state in ("secure_entry_unavailable", "credential_required", "invalid_key"):
        # No invented tool/schema: the verified secure-entry action is a T1 gate.
        return {"type": "offer_legacy", "requires_user_choice": True,
                "argv": ["snaplii", "--base-url", normalize_base_url(origin), "init"]}
    secure = host == "muse" or auth_method == "vault"
    if secure:
        try:
            validate_vault_origin(origin)
        except ConfigError:
            return {"type": "stop", "reason": "secure_origin_not_allowed"}
    argv = ["snaplii", "--base-url", normalize_base_url(origin), "init"]
    if secure:
        argv.append("--vault-auth")
    action = {"type": "run_cli", "argv": argv}
    if secure:
        action["instruction"] = MUSE_AUTH_INSTRUCTION
    return action
