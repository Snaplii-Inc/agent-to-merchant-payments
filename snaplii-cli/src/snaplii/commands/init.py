import hashlib
import sys

import click

from snaplii.client import GatewayClient
from snaplii.output import print_json


def _derive_agent_id(api_key: str) -> str:
    """Derive a stable agent_id from api_key: 'agent-' + first 8 chars of MD5."""
    digest = hashlib.md5(api_key.encode()).hexdigest()
    return f"agent-{digest[:8]}"


@click.command("init")
@click.option("--agent-id", default=None, help="Agent ID (optional — auto-derived from API key if omitted)")
@click.pass_context
def init_cmd(ctx, agent_id):
    """Login with API key and store credentials.

    API key is read from hidden stdin input — never passed as a CLI argument
    to avoid exposure in shell history and process listings.
    The API key is used only to obtain a token and is NOT stored.
    """
    client: GatewayClient = ctx.obj["client"]
    store = ctx.obj["config_store"]

    if not sys.stdin.isatty():
        # Piped input (e.g. echo "key" | snaplii init) — read silently
        api_key = sys.stdin.readline()
    else:
        try:
            api_key = click.prompt("API key", hide_input=True)
        except (click.Abort, EOFError):
            api_key = click.prompt("API key (input will be visible)")

    api_key = api_key.strip()
    if not api_key:
        raise click.ClickException("API key cannot be empty.")

    if not agent_id:
        agent_id = _derive_agent_id(api_key)

    store.set("agent_id", agent_id)
    # API key is NOT stored — only used to obtain a token
    resp = client.login(agent_id, api_key)
    safe = {k: v for k, v in resp.items() if k not in ("access_token", "token_type", "expires_in")}
    safe["status"] = "authenticated"
    safe["agent_id"] = agent_id
    print_json(safe)
