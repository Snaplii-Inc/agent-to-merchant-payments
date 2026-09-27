import hashlib
import secrets
import sys

import click

from snaplii import auth
from snaplii.client import GatewayClient
from snaplii.exceptions import AuthError, ConfigError
from snaplii.output import print_json


def _derive_agent_id(api_key: str) -> str:
    """Derive a stable agent_id from api_key: 'agent-' + first 8 chars of MD5."""
    digest = hashlib.md5(api_key.encode()).hexdigest()
    return f"agent-{digest[:8]}"


def _require_valid_agent_id(agent_id: str) -> None:
    # Validate before any network exchange, so a bad ID never mints a token
    # that is then discarded locally.
    if not auth.valid_agent_id(agent_id):
        raise ConfigError("Invalid agent ID.")


@click.command("init")
@click.option("--agent-id", default=None, help="Agent ID (optional; generated or reused when omitted)")
@click.option("--vault-auth", is_flag=True, default=False,
              help="Authenticate using Muse's secure credential store. Does not prompt for a raw API key.")
@click.option("--legacy-auth", is_flag=True, default=False,
              help="Explicitly choose the original API-key input instead of Muse secure authentication.")
@click.pass_context
def init_cmd(ctx, agent_id, vault_auth, legacy_auth):
    """Login with API key and store credentials.

    API key is read from hidden stdin input — never passed as a CLI argument
    to avoid exposure in shell history and process listings.
    The API key is used only to obtain a token and is NOT stored.
    With --vault-auth the key comes from the secure credential store instead.
    The agent ID is reused, or generated on first successful initialization.
    """
    client: GatewayClient = ctx.obj["client"]
    store = ctx.obj["config_store"]
    if vault_auth and legacy_auth:
        raise click.UsageError("Choose only one of --vault-auth and --legacy-auth.")
    if not legacy_auth and client.auth_status()["host"] == "muse":
        vault_auth = True

    if vault_auth:
        agent_id = agent_id or store.get("agent_id") or "agent-" + secrets.token_hex(4)
        _require_valid_agent_id(agent_id)
        client.login_via_vault(agent_id)
        print_json({"status": "authenticated", **client.auth_status()})
        return

    try:
        if sys.stdin.isatty():
            api_key = click.prompt("API key", hide_input=True, err=True)
        else:
            # Explicit stdin input remains supported without echoing a secret or
            # mixing a prompt into the JSON result consumed by an agent.
            api_key = sys.stdin.readline()
    except (click.Abort, EOFError):
        raise AuthError("Authentication was cancelled.", auth_state="cancelled",
                        reason_code="cancelled", next_action={"type": "stop", "reason": "cancelled"}) from None

    api_key = api_key.strip()
    if not api_key:
        raise AuthError("API key cannot be empty.", auth_state="auth_required",
                        reason_code="api_key_missing", next_action={"type": "stop", "reason": "api_key_missing"})

    if not agent_id:
        agent_id = _derive_agent_id(api_key)
    _require_valid_agent_id(agent_id)

    # API key is NOT stored — only used to obtain a token
    client.login(agent_id, api_key)
    print_json({"status": "authenticated", **client.auth_status()})
