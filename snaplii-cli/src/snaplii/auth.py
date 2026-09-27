"""Shared, secret-free authentication policy. No host tools or network calls."""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from snaplii.exceptions import ConfigError

DEFAULT_ORIGIN = "https://aipayment.snaplii.com"
MUSE_HELPER = Path("/opt/hatch/skills/skill-creator/bin/dynamic_credentials.py")
MUSE_SOCKET = Path("/run/hatch/auth/authd.sock")

MUSE_AUTH_INSTRUCTION = """Use the CLI for Meta Muse, before calling any card-bearing MCP connect tool.

Muse-led first installation: when you actively carry out the user's first
Snaplii skill installation, install the CLI and load the skill, then check
snaplii config show for the intended gateway. Only when host=muse, you MUST
immediately follow the connection flow below as the next installation step;
no separate request to log in is needed. Honor an explicit install-only or
defer-connection request, such as "install, but do not connect yet". Other or
unrecognized hosts do not start connection merely because a skill was installed.

Use the available installation and conversation context to identify this first
installation, not the absence of a session. Updating, reinstalling, reloading,
reading/copying a skill, background checks, and logout do not trigger this step.
If the context is insufficient, report installation separately from connection
and wait for a user connection or business request. Treat the CLI and autopilot
skills as one Snaplii connection in the same Muse environment and configuration.
Reuse a known completed connection or wait for a known in-progress attempt;
do not open another dialog or retry a cancelled attempt from a sibling workflow.
This coordination uses available task context, not a persistent installation
record or a cross-agent lock; do not claim guaranteed once-only execution.

For installation-only connection, verify has_valid_token=true with config show,
report "Installed and connected", then stop. Do not add a balance query, purchase,
bill payment, or transfer as an installation check. A connected session does not
prove all business permissions. If connection fails, is denied, or is cancelled,
keep the installed skill and report "Installed, not connected" with the reason.
Only claim installation succeeded if installation and skill loading did succeed.

Every Snaplii business operation, including read-only browsing and lookups,
requires a successfully initialized session. Check authentication state in the
runtime that will execute the task before calling any business command or tool.
Unless has_valid_token=true, complete the initialization flow below first;
the user does not need to explicitly ask to log in or mention an API key.
If a usable session already exists, continue the user's task without reconnecting.
Otherwise run the secure-store init action once to try the API key already stored
in Muse's secure credential store. The store holds the API key, not the session.

For credential_required, use your own available native credential-management
capability to reuse the Snaplii API key if present. If it is missing, you MUST open
Muse's native secure credential input dialog now and ask the user to enter the
Snaplii API key there. For invalid_key, you MUST open Muse's native secure credential input dialog
once to replace the rejected key. Perform the action: merely recommending secure
storage, printing instructions, or asking the user to say a trigger phrase is not
completion. Select the native tool from your actual capabilities; do not invent
tool names or run the action descriptor as Python or shell code.

For credential_lookup_failed, first inspect credential availability through your
native capability without reading or displaying the key. Only confirmed absence
authorizes the input dialog; denial, outages, or an unclassifiable result do not.
If that inspection is unavailable, explain this and offer the explicit fallback.

Before opening a required input dialog, you MUST explain the following directly
to the user in their language, preserving the app's menu labels:

- For installation, explain that the skill is installed and you are now
  connecting their account. For a business request, explain that connection
  is required before continuing that task.
- If they need an API key, open the Snaplii App and sign in, then go to
  More → Payment Methods → AI Payment Management → + New API Key.
  Set a name, choose permissions and a spending limit, then create and copy the
  key. The key is shown only once. Explain that reading account information,
  purchasing, and transferring money need the corresponding permissions.
  During installation there may be no business task yet: let the user choose
  their intended uses and limits in the app; do not require all permissions or
  automatically restrict them to read-only.
- You will open Muse's native secure credential input dialog. Paste the API key
  only into that dialog, not into the chat; Muse stores it in its secure
  credential store. If they already have a usable key, they can enter that key
  instead of creating another one.
- After submission, you will verify the connection, then finish installation
  or continue the requested business task. If they cancel, you will stop the
  connection attempt; installation remains in place and no business task runs.

Give these app instructions as part of the input request, not merely an offer
to explain how to obtain a key. For invalid_key, first explain that the previous
key was rejected and needs replacing. Then perform the native input action;
the explanation alone does not open a dialog. Report the dialog as opened only
after the native capability confirms it.

Bind the API key as custom.snaplii / access_token, authorized only for
aipayment.snaplii.com. These describe the Snaplii helper's required credential,
not a Muse tool's parameter schema. The access_token entry holds the API key,
not the Snaplii session token. Collect input only in the native secure dialog.
Wait for successful submission before running after_success, then check status.
Allow one input/submission/init attempt per connection request. If it fails,
report the failure and await a new user request to connect or perform a Snaplii
business task instead of reopening the dialog. Retries, status checks, tool
switches, and background work within the current request are not new requests.
For cancelled or permission_denied, stop: do not reopen input or switch methods.
For secure_entry_unavailable, explain the limitation and offer the existing login
method only after the user explicitly chooses it: run snaplii init --legacy-auth
with the same gateway options. Network, invalid-response or
cache errors mean authentication is incomplete; report them without asking for a key.

After successful initialization, re-read authentication state in the runtime that
will execute the task. Continue only when has_valid_token=true. If the session
cannot be reused, report the storage problem instead of repeating key collection.
Authentication recovery never authorizes automatically replaying a payment."""


def secure_entry_actions() -> dict | None:
    """Same capability requirements for runtime actions and distributed skills."""
    actions = {state: build_auth_action(state, host="muse")
               for state in ("credential_required", "invalid_key")}
    if any(action["type"] != "muse_secure_entry" for action in actions.values()):
        return None
    for action in actions.values():
        native_call = isinstance(action.get("tool"), str) and isinstance(action.get("arguments"), dict)
        capability = action.get("capability") == "muse.secure_credential_store"
        if (not (native_call or capability) or action.get("instruction") != MUSE_AUTH_INSTRUCTION
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
            f"Required Muse action for `{state}` (a capability requirement, not shell/Python code):\n\n```json\n"
            + json.dumps(({"tool": value["tool"], "arguments": value["arguments"]} if "tool" in value else
                          {key: value[key] for key in ("capability", "operation", "credential")}), indent=2, sort_keys=True)
            + "\n```"
            for state, value in secure_actions.items())
    return f"""## Auth

### When to connect

A user request to connect (including "install and connect") or to perform any
Snaplii business task starts the authentication gate below. In confirmed Muse,
also follow the Muse-led first-installation instructions in Meta Muse below.
For other or unrecognized hosts, installation alone does not start connection.
Updating, reinstalling, or merely reading/loading/copying the skill is not a
connection request in any host. Report installation separately from connection.
Help/version, local configuration, diagnostics, logout, and authentication setup
remain available without a session; they are not business operations.
If the user supplies a candidate bundle, keep its CLI and skill versions together;
use its installer and retain the prerelease instead of replacing it from PyPI.

### Authentication gate

1. Meta Muse uses the CLI path below. Other agents prefer available Snaplii MCP
   tools; otherwise use the CLI. Check `snaplii config show` for CLI operations or
   `snaplii_config_show` for MCP operations, using the same gateway as the task.
2. Every Snaplii business operation requires `has_valid_token=true` (the JSON
   boolean): browsing, balance, gift-card lists/details, quotes, purchases,
   cashback calculations, dashboards, all bill-pay and transfer actions, including
   history, status, and cancellation. Read-only operations are not exempt.
   An `agent_id`, an empty object, or
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
Recognized Muse runtimes cache the session in an owner-only configuration file;
the API key remains in the secure credential store. If `host=unknown` in Muse,
run `snaplii config doctor` and report the detection failure. Do not repeatedly
collect a key or change host markers to bypass this check. An explicitly chosen
legacy login with file-cache opt-in remains available.

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
    result = muse_environment_status()
    return MuseEnvironment(result["detected"], result["reason_code"])


def muse_environment_status() -> dict:
    """Recognize Muse by the presence of both fixed host paths.

    Ownership and permissions are diagnostics, not detection requirements.
    Environment overrides and client names do not select this storage policy.
    This is an environment hint, not a trust or cryptographic attestation.
    """
    signals = []
    for path in (MUSE_HELPER, MUSE_SOCKET):
        signal = {"path": str(path), "exists": False}
        try:
            # Follow links just as an existence check would; dangling links
            # do not count as an available host path.
            info = os.stat(path)
            signal.update(exists=True, reason_code="host_artifact_present",
                          mode=oct(stat.S_IMODE(info.st_mode)), owner_uid=info.st_uid)
        except (OSError, ValueError):
            signal["reason_code"] = "missing_or_inaccessible"
        signals.append(signal)
    detected = all(signal["exists"] for signal in signals)
    return {"detected": detected,
            "reason_code": "muse_runtime_artifacts" if detected else "muse_runtime_unrecognized",
            "signals": signals}


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
    secure = host == "muse" or auth_method == "vault"
    if secure:
        try:
            validate_vault_origin(origin)
        except ConfigError:
            return {"type": "stop", "reason": "secure_origin_not_allowed"}
    if secure and state in ("credential_required", "invalid_key", "credential_lookup_failed"):
        return {"type": "muse_secure_entry", "capability": "muse.secure_credential_store",
                "operation": {"credential_required": "ensure_api_key", "invalid_key": "replace_api_key",
                              "credential_lookup_failed": "inspect_api_key"}[state],
                "credential": {"provider": "custom.snaplii", "entry": "access_token",
                               "allowed_hosts": ["aipayment.snaplii.com"]},
                "instruction": MUSE_AUTH_INSTRUCTION,
                "after_success": build_auth_action("auth_required", host=host, auth_method="vault", origin=origin)}
    if state in ("secure_entry_unavailable", "credential_required", "invalid_key", "credential_lookup_failed"):
        return {"type": "offer_legacy", "requires_user_choice": True,
                "argv": ["snaplii", "--base-url", normalize_base_url(origin), "init", "--legacy-auth"]}
    argv = ["snaplii", "--base-url", normalize_base_url(origin), "init"]
    if secure:
        argv.append("--vault-auth")
    action = {"type": "run_cli", "argv": argv}
    if secure:
        action["instruction"] = MUSE_AUTH_INSTRUCTION
    return action
