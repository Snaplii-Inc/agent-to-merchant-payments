from __future__ import annotations

import shlex
import time
import unicodedata

import click

from snaplii import auth
from snaplii.client import GatewayClient
from snaplii.config_store import AGENT_TOKEN, CONNECT_TOKEN, ConfigStore
from snaplii.exceptions import ConfigError, ConnectError, GatewayApiError, GatewayConnectionError
from snaplii.output import print_json

# How an agent connects to a user's Snaplii account by phone (`snaplii agent ...`), side by side
# with the API-key session of `snaplii init`. It needs no browser and no API key: the agent has this
# CLI, and the user has their phone. The same flow signs in a user who has an account and signs up
# one who doesn't. Every sign-in is a new request:
#
#   1. Ask the gateway to sign in, with the agent's name and the user's mobile number. If this
#      configuration still holds a long-term token from the same gateway, it goes along with the
#      request, so the user's approval replaces that connection, with its daily limit, instead of
#      adding a second one. The token held keeps working until then.
#   2. The gateway texts the user a sign-in link, and answers a temporary token and a match code.
#   3. The agent tells the user that code: the text message doesn't contain it. The user opens the
#      link on their phone, types the code, and approves.
#   4. Swap the temporary token for the long-term token, once, and keep it in place of the one held.
#   5. From then on the long-term token signs the agent in on every `snaplii agent` call.
#   6. `snaplii agent disconnect` ends the connection: the token stops working and is removed.
#
# The tokens are kept where this configuration keeps its API-key session (the system keychain, or
# the owner-only config file on Muse or with the insecure opt-in), are sent only to the gateway
# the sign-in started at, and are never printed. The agent never asks the user for anything that
# arrives by text.

AGENT_NAME = "agent_name"  # which agent the long-term token belongs to
AGENT_ORIGIN = "agent_origin"  # the gateway the sign-in started at: the only one the tokens go to
CONNECT_AGENT_NAME = "connect_agent_name"  # which agent the temporary token was asked for
CONNECT_MATCH_CODE = "connect_match_code"  # what the user types to approve; not a secret, so it is printed
CONNECT_TEXTED_TO = "connect_texted_to"  # the phone the link went to, masked, so a later run can say it again
_WAITING_SIGN_IN = (CONNECT_TOKEN, CONNECT_AGENT_NAME, CONNECT_MATCH_CODE, CONNECT_TEXTED_TO)

CONNECT_HINT = "Run 'snaplii agent connect --agent NAME --phone NUMBER' and ask the user to approve."


@click.command("connect")
@click.option("--agent", required=True, help="This agent's name, e.g. muse or grok")
@click.option(
    "--phone",
    default=None,
    help="The user's mobile number, e.g. '416 555 0100': Snaplii texts the sign-in link to it. "
    "Needed to start a sign-in; not with --resume.",
)
@click.option(
    "--region",
    type=click.Choice(["CA", "US"], case_sensitive=False),
    default=None,
    help="How to read a number given without +1 (default CA)",
)
@click.option(
    "--resume",
    is_flag=True,
    help="Go on waiting for the request an earlier run started, instead of starting a new one.",
)
@click.option(
    "--wait/--no-wait",
    default=True,
    help="Wait for the user to approve (default), or return at once with the code to tell the user; "
    "run the command again with --resume to go on waiting",
)
@click.option(
    "--timeout", type=int, default=600, show_default=True, help="Seconds to wait before stopping for now"
)
@click.pass_context
def agent_connect_cmd(ctx, agent, phone, region, resume, wait, timeout):
    """Connect this agent to a user's Snaplii account by phone.

    Snaplii texts a sign-in link to --phone, and this prints a code to tell the user. Once they
    open the link and approve it with the code, this agent's long-term token is kept (never printed)
    and the other 'snaplii agent' commands use it. A phone with no Snaplii account signs up the
    same way.

    Every run starts a new sign-in. The token held keeps working until the user approves the new
    one, which then replaces it. --resume goes on waiting for an earlier run's request.
    """
    client: GatewayClient = ctx.obj["client"]
    store: ConfigStore = ctx.obj["config_store"]

    connected_agent = store.get(AGENT_NAME)
    if connected_agent and agent_id(connected_agent) != agent_id(agent):
        raise ConfigError(
            f"This configuration belongs to agent '{connected_agent}'. Use another configuration file "
            f"for '{agent}': set SNAPLII_CONFIG_PATH."
        )
    # Both checked before anything is sent: a run that couldn't keep the token must not text the
    # user or drop the token held.
    auth.require_agent_connect_origin(client.origin)
    store.agent_token_storage()

    same_gateway = store.get(AGENT_ORIGIN) == client.origin
    waiting_token = (
        store.get_agent_secret(CONNECT_TOKEN)
        if same_gateway and agent_id(store.get(CONNECT_AGENT_NAME) or "") == agent_id(agent)
        else None
    )
    if resume and waiting_token:
        connect_token = waiting_token
        interval = 3
        click.echo("Still waiting for the user to approve...", err=True)
        _say_what_to_tell(store.get(CONNECT_TEXTED_TO), store.get(CONNECT_MATCH_CODE))
    else:
        if not phone:
            raise click.UsageError(
                "--phone is needed to start a sign-in: the user's mobile number, e.g. --phone '416 555 0100'."
            )
        if waiting_token:
            # The user may already have approved the earlier request: then it is collected, and
            # nobody is texted again. Starting another would leave that connection behind.
            approved, _ = _collect_waiting_sign_in(client, store)
            if approved:
                print_json({"status": "connected", **connection_summary(approved)})
                return
            waiting_token = store.get_agent_secret(CONNECT_TOKEN)  # gone if it can't be used any more
        if resume:
            click.echo("No earlier request to go on with: starting a new sign-in.", err=True)
        connect_token, interval = _start_sign_in(client, store, agent, phone, region, replaces=waiting_token)

    deadline = time.monotonic() + timeout
    while True:
        try:
            result = client.collect_agent_token(connect_token)
        except GatewayApiError as e:
            if e.status_code == 401:  # the swap needs no token either
                raise ConnectError(_NO_PHONE_CONNECTIONS) from e
            if e.body.get("code") != "invalid-connect-token":
                raise
            # The temporary token can't be used any more. The token held, if any, still works.
            store.update_agent_connection(remove=_WAITING_SIGN_IN)
            raise ConnectError(
                "This sign-in request can't be used any more: it expired, a newer one replaced it, or its "
                "token was already collected. Run connect again to start a new one."
            )
        if result.get("status") == "connected":
            _keep_agent_token(store, result, agent)
            print_json({"status": "connected", **connection_summary(result)})
            return
        if not wait or time.monotonic() + interval > deadline:
            pending = {
                "status": "pending",
                "message": "The user hasn't approved yet. Tell them the match code, then run "
                f"'snaplii agent connect --agent {_cli_name(agent)} --resume' to keep waiting.",
            }
            if store.get(CONNECT_MATCH_CODE):
                pending["match_code"] = store.get(CONNECT_MATCH_CODE)
            if store.get(CONNECT_TEXTED_TO):
                pending["texted_to"] = store.get(CONNECT_TEXTED_TO)
            print_json(pending)
            return
        time.sleep(interval)


@click.command("connection")
@click.pass_context
def agent_connection_cmd(ctx):
    """Sign in with the phone connection's long-term token and show this agent's daily limit."""
    client: GatewayClient = ctx.obj["client"]
    store: ConfigStore = ctx.obj["config_store"]

    token = store.get_agent_secret(AGENT_TOKEN)
    if not token:
        raise ConnectError("This agent isn't connected by phone yet. " + CONNECT_HINT)
    try:
        connection = client.get_agent_connection(token)
    except GatewayApiError as e:
        raise_if_not_signed_in(e)
        raise
    print_json({"status": "connected", **connection_summary(connection)})


@click.command("disconnect")
@click.pass_context
def agent_disconnect_cmd(ctx):
    """Disconnect this agent's phone connection from the user's Snaplii account.

    Its long-term token and its access to Snaplii end at once, and the token is removed. The agent's
    daily limit and what it bought stay: if it connects again, it keeps them. The API-key session of
    'snaplii init' is not touched. A sign-in the user already approved is collected first, so the
    connection it replaced is the one that ends.
    """
    client: GatewayClient = ctx.obj["client"]
    store: ConfigStore = ctx.obj["config_store"]

    try:
        approved, still_waiting = _collect_waiting_sign_in(client, store)
    except (GatewayApiError, GatewayConnectionError):
        # Ending the connection held matters more than checking the request: go on without it.
        approved, still_waiting = None, store.get_agent_secret(CONNECT_TOKEN) is not None
    token = approved["agent_token"] if approved else store.get_agent_secret(AGENT_TOKEN)
    waiting_note = (
        " A sign-in request was still waiting for the user: tell them not to approve its link."
        if still_waiting else ""
    )
    if not token:
        # The request is kept: it replaces no connection, so if the user approves it after all, the
        # next disconnect collects its token and ends that connection.
        raise ConnectError(
            "This agent isn't connected by phone, so there is nothing to disconnect." + waiting_note
            + (" If they did, run disconnect again to end that connection." if still_waiting else "")
        )
    agent = store.get(AGENT_NAME)
    try:
        client.disconnect_agent(token)
        message = (
            "This agent is disconnected. To connect it again, run "
            f"'snaplii agent connect --agent {_cli_name(agent) if agent else 'NAME'} --phone NUMBER' "
            "and ask the user to approve."
        )
    except GatewayApiError as e:
        if not token_stopped_working(e):
            # The token is kept, so running disconnect again can still end it.
            raise_if_not_signed_in(e)
            raise
        message = (
            "This agent's token had already stopped working: it was disconnected, "
            "or it was connected again from somewhere else."
        )
    store.update_agent_connection(remove=(AGENT_TOKEN, AGENT_NAME, AGENT_ORIGIN, *_WAITING_SIGN_IN))
    print_json({"status": "disconnected", "agent": agent, "message": message + waiting_note})


def _start_sign_in(client: GatewayClient, store: ConfigStore, agent: str, phone: str,
                   region: str | None, replaces: str | None) -> tuple[str, int]:
    """Starts a new sign-in request, which texts the user, and keeps what it waits for.

    A long-term token held from this gateway goes along and is kept: the user's approval replaces
    that connection, and until then the token still works. One from another gateway is dropped, as
    this sign-in makes this gateway the only one the tokens go to. An earlier unfinished request
    (`replaces`) is ended.
    """
    same_gateway = store.get(AGENT_ORIGIN) == client.origin
    held_token = store.get_agent_secret(AGENT_TOKEN) if same_gateway else None
    started = _call_connect(lambda: client.start_agent_connect(
        agent, phone, region=region, agent_token=held_token, replaces=replaces))
    store.update_agent_connection(
        tokens={CONNECT_TOKEN: started["connect_token"]},
        fields={
            CONNECT_AGENT_NAME: agent,
            CONNECT_MATCH_CODE: started.get("match_code"),
            CONNECT_TEXTED_TO: started.get("texted_to"),
            AGENT_ORIGIN: client.origin,
        },
        remove=_WAITING_SIGN_IN if same_gateway else (AGENT_TOKEN, AGENT_NAME, *_WAITING_SIGN_IN),
    )
    _say_what_to_tell(started.get("texted_to"), started.get("match_code"))
    return started["connect_token"], int(started.get("interval", 3))


def _keep_agent_token(store: ConfigStore, result: dict, agent: str | None) -> None:
    """Keeps the long-term token of an approved sign-in, in place of the one held."""
    store.update_agent_connection(
        tokens={AGENT_TOKEN: result["agent_token"]},
        fields={AGENT_NAME: result.get("agent", agent)},
        remove=_WAITING_SIGN_IN,
    )


def _collect_waiting_sign_in(client: GatewayClient, store: ConfigStore) -> tuple[dict | None, bool]:
    """Asks once about the sign-in this configuration waits for at this gateway.

    Returns the gateway's answer when the user approved it (its long-term token is kept), and whether
    it is still waiting for the user. A request that can't be used any more is forgotten.
    """
    connect_token = store.get_agent_secret(CONNECT_TOKEN) if store.get(AGENT_ORIGIN) == client.origin else None
    if not connect_token:
        return None, False
    try:
        result = client.collect_agent_token(connect_token)
    except GatewayApiError as e:
        if e.body.get("code") != "invalid-connect-token":
            raise
        store.update_agent_connection(remove=_WAITING_SIGN_IN)
        return None, False
    if result.get("status") == "connected":
        _keep_agent_token(store, result, store.get(CONNECT_AGENT_NAME))
        return result, False
    return None, True


def _say_what_to_tell(texted_to: str | None, code: str | None) -> None:
    """Tells the agent where the link went, and the code its user has to type on their phone."""
    if not texted_to and not code:
        # A gateway in its dev sign-in mode: it approves the request itself.
        click.echo(
            "No text and no code: this gateway signs agents in as its configured test user.",
            err=True,
        )
        return
    if texted_to:
        click.echo(f"Snaplii texted a sign-in link to {texted_to}.", err=True)
    if code:
        click.echo(
            f"Tell the user this code. They open the link and type it there, to approve: {code}",
            err=True,
        )


def _call_connect(request):
    """Starts a sign-in. Starting one needs no token, so a 401 there means the gateway doesn't take
    phone connections at all."""
    try:
        return request()
    except GatewayApiError as e:
        if e.status_code == 401:
            raise ConnectError("Nothing was sent to the user's phone. " + _NO_PHONE_CONNECTIONS) from e
        raise


_NO_PHONE_CONNECTIONS = (
    "This gateway doesn't take phone connections right now. Connect with an API key ('snaplii init') "
    "instead, or try again later."
)


def token_stopped_working(e: GatewayApiError) -> bool:
    """Whether the gateway refused the long-term token itself: the agent was disconnected, or a later
    connect replaced it. A gateway that doesn't take phone connections answers 401 too, without naming
    the agent's token, and the token may work again there."""
    message = e.body.get("message")
    return e.status_code == 401 and isinstance(message, str) and "agent token" in message.lower()


def raise_if_not_signed_in(e: GatewayApiError) -> None:
    """Turns a 401 from a call made with the long-term token into what the agent does about it."""
    if token_stopped_working(e):
        # The user may have approved the sign-in this configuration waits for, which replaced the
        # token: asked about once here, so the agent never has to guess.
        ctx = click.get_current_context(silent=True)
        if ctx and ctx.obj and "config_store" in ctx.obj:
            try:
                approved, still_waiting = _collect_waiting_sign_in(ctx.obj["client"], ctx.obj["config_store"])
            except (GatewayApiError, GatewayConnectionError):
                approved, still_waiting = None, False
            if approved:
                raise ConnectError(
                    "The user approved this agent's new sign-in, which replaced its token. The new token is "
                    "kept now: run the command again."
                ) from e
            if still_waiting:
                agent = ctx.obj["config_store"].get(CONNECT_AGENT_NAME) or "NAME"
                raise ConnectError(
                    "This agent's token stopped working, and the sign-in it waits for isn't approved yet. "
                    "Ask the user to open the link texted to them and approve it, then run "
                    f"'snaplii agent connect --agent {_cli_name(agent)} --resume'."
                ) from e
        raise ConnectError(
            "This agent isn't connected any more: it was disconnected, "
            "or it was connected again from somewhere else. " + CONNECT_HINT
        ) from e
    if e.status_code == 401:
        raise ConnectError(
            "This gateway didn't sign the agent in, and didn't say its token stopped working: it may not "
            "take phone connections right now. The token is kept; try again later."
        ) from e


def _cli_name(name: str) -> str:
    """The agent's name as it goes in a command to copy: the gateway's form, quoted if it needs it."""
    return shlex.quote(agent_id(name))


def agent_id(name: str) -> str:
    """The agent a name stands for, as the gateway reads it: lower case, without control characters
    or the spaces around it, at most 32 characters. 'Muse' and 'muse' are one agent."""
    kept = "".join(c for c in name.lower() if unicodedata.category(c) != "Cc").strip()
    return kept[:32]


def connection_summary(connection: dict) -> dict:
    """What is safe to print about a phone connection: never a token."""
    cents = connection.get("daily_limit_cents")
    currency = connection.get("currency")
    summary = {
        "agent": connection.get("agent"),
        "daily_limit_cents": cents,
        "currency": currency,
    }
    if isinstance(cents, int) and currency:
        summary["daily_limit"] = format_money(cents, currency)
    for name in ("connected_at", "can_buy"):
        if name in connection:
            summary[name] = connection[name]
    if connection.get("can_buy") is False:
        summary["message"] = (
            "This connection has no access to Snaplii of its own, so the agent can't buy until it "
            "connects again. " + CONNECT_HINT
        )
    return summary


def format_money(cents: int, currency: str | None) -> str:
    symbol = {"CAD": "CA$", "USD": "US$"}.get(currency or "", (currency or "") + " ")
    return f"{symbol}{cents / 100:.2f}"
