from __future__ import annotations

import time
import uuid

import click

from snaplii.client import GatewayClient
from snaplii.commands.agent_connection import CONNECT_HINT, format_money, raise_if_not_signed_in
from snaplii.config_store import AGENT_TOKEN, ConfigStore
from snaplii.exceptions import ConnectError, GatewayApiError
from snaplii.output import print_json

# How an agent connected by phone buys a gift card for its user, under its own daily limit:
#
#   1. `snaplii agent balance`: the user's Snaplii Cash and what is left of this agent's daily limit.
#      `snaplii agent catalog`: the brands Snaplii sells; `snaplii agent catalog BRAND_ID`: a brand's
#      cards, each with the item_id and price to buy it with.
#   2. `snaplii agent buy --item-id ID --price 25`: starts an order. Its status says what happened:
#        PAID          the card is in the user's Snaplii wallet
#        NEEDS_TOP_UP  Snaplii Cash is short by gap_cents: `snaplii agent top-up AMOUNT` (the user
#                      pays on the link texted to them), then `snaplii agent order ORDER_ID --continue`
#        OVER_LIMIT    over this agent's daily limit: the user buys it in the Snaplii app. Final
#        REFUSED       Snaplii refused it; nothing was charged. Final
#        UNKNOWN       Snaplii didn't confirm the payment: never order again
#        EXPIRED       waited for a top-up too long and was closed; nothing was charged. Final
#
# `snaplii agent top-up 50` asks the user to add 50 dollars to their Snaplii Cash. The gateway texts
# the pay link to the phone that approved the agent (texted_to); where it may also show it (local
# runs, staging) it answers it as pay_url, and this prints it for the agent to give to the user too.
# The user pays there with Apple Pay or Google Pay; `--payment-method alipay` makes it Alipay's page
# instead. It returns once the top-up is made, with its id. An agent that asked too often in the
# last hour can't ask again yet.
# `snaplii agent top-up-status ID` then shows where the top-up is:
#        CREATED    waiting for the user to pay
#        PAID       the user paid; Snaplii is adding the money to Snaplii Cash
#        CREDITED   the money is in Snaplii Cash. Final
#        EXPIRED    not paid before its expires_at (the gateway sets how long that is). Final
#        FAILED     it couldn't be started, its link couldn't be texted, or the payment failed;
#                   nobody was charged. Final
#        REVIEW     Snaplii is checking the payment by hand
#        CANCELLED  taken back before anybody paid. Final
# `snaplii agent top-up-cancel ID` takes back a top-up nobody paid yet: one unpaid top-up is open at
# a time, so this is how the agent asks for another amount or payment method without waiting.
#
# What the agent does next is the gateway's to say: each order and top-up comes with a next_step
# sentence. For the statuses whose sentence names the gateway's own API calls, this words it with
# this CLI's commands instead, as an agent uses the CLI and never the API; any other is printed as
# it is.

# The statuses a command keeps asking the gateway about, because they change within seconds or
# minutes. Not every status that can still change: an order in NEEDS_TOP_UP waits for a top-up, and
# a top-up in REVIEW for a person at Snaplii.
_ORDER_STATUSES_TO_POLL = ("PAYING",)
_ORDER_POLL_INTERVAL_SECONDS = 2
_TOP_UP_STATUSES_TO_POLL = ("CREATED", "PAID")
_TOP_UP_POLL_INTERVAL_SECONDS = 5


@click.command("balance")
@click.pass_context
def agent_balance_cmd(ctx):
    """Show the user's Snaplii Cash and what is left of this agent's daily limit."""
    client, agent_token = _client_and_agent_token(ctx)
    balance = _call_as_connected_agent(lambda: client.get_agent_balance(agent_token))
    for name in ("cash", "daily_limit", "spent_today", "available_today"):
        cents = balance.get(name + "_cents")
        if isinstance(cents, int):
            balance[name] = format_money(cents, balance.get("currency"))
    print_json(balance)


@click.command("catalog")
@click.argument("brand_id", required=False)
@click.pass_context
def agent_catalog_cmd(ctx, brand_id):
    """List the gift card brands Snaplii sells, or one brand's cards (BRAND_ID).

    A card's item_id and price are what 'snaplii agent buy' takes.
    """
    client, agent_token = _client_and_agent_token(ctx)
    if brand_id:
        print_json(_call_as_connected_agent(lambda: client.get_agent_brand(agent_token, brand_id)))
    else:
        print_json(_call_as_connected_agent(lambda: client.get_agent_catalog(agent_token)))


@click.command("buy")
@click.option("--item-id", required=True, help="Item ID: {cardBrandId}-{cardTemplateId}")
@click.option("--price", required=True, help="Price in dollars, e.g. 25")
@click.option(
    "--key",
    default=None,
    help="Idempotency key of this purchase. Pass the key an earlier run printed to ask about "
    "that order again instead of buying a second time.",
)
@click.option("--timeout", type=int, default=60, show_default=True, help="Seconds to wait while Snaplii is paying")
@click.pass_context
def agent_buy_cmd(ctx, item_id, price, key, timeout):
    """Buy a gift card for the user from their Snaplii Cash, under this agent's daily limit.

    Prints the order and what to do next. Never buys twice for the same --key.
    """
    client, agent_token = _client_and_agent_token(ctx)
    key = key or "cli-" + uuid.uuid4().hex
    # Printed first, so a run that dies before the answer can still be asked about with --key.
    click.echo(f"Ordering with idempotency key {key}", err=True)
    order = _call_as_connected_agent(lambda: client.create_agent_order(agent_token, item_id, price, key))
    print_json({"idempotency_key": key, **_settled(client, agent_token, order, timeout)})


@click.command("order")
@click.argument("order_id")
@click.option(
    "--continue",
    "resume",
    is_flag=True,
    help="Check the order again after the user topped up their Snaplii Cash",
)
@click.option("--timeout", type=int, default=60, show_default=True, help="Seconds to wait while Snaplii is paying")
@click.pass_context
def agent_order_cmd(ctx, order_id, resume, timeout):
    """Show an order, or continue one that waited for a top-up (--continue)."""
    client, agent_token = _client_and_agent_token(ctx)
    if resume:
        order = _call_as_connected_agent(lambda: client.continue_agent_order(agent_token, order_id))
    else:
        order = _call_as_connected_agent(lambda: client.get_agent_order(agent_token, order_id))
    print_json(_settled(client, agent_token, order, timeout))


@click.command("top-up")
@click.argument("amount")
@click.option(
    "--payment-method",
    "payment_method",
    type=click.Choice(["stripe", "alipay"], case_sensitive=False),
    default=None,
    help="How the user pays on the texted link: stripe (the gateway's default: Apple Pay or Google Pay) "
    "or alipay (Alipay's page)",
)
@click.option(
    "--wait/--no-wait",
    default=False,
    help="Wait until the top-up settles, or return once it is made (default); "
    "follow it with 'snaplii agent top-up-status ID'",
)
@click.option(
    "--timeout", type=int, default=600, show_default=True, help="With --wait: seconds to wait for the user to pay"
)
@click.pass_context
def agent_top_up_cmd(ctx, amount, payment_method, wait, timeout):
    """Ask the user to add AMOUNT dollars (such as 50 or 50.25) to their Snaplii Cash.

    The gateway texts the user the pay link: by default a page to pay on with Apple Pay or Google
    Pay, with --payment-method alipay Alipay's page. Where the gateway may also show it, this prints
    it to give to the user too. The user can pay until the top-up's expires_at.

    Follow it with 'snaplii agent top-up-status ID'. Asking again for the same amount and payment
    method while the user can still pay gives the same top-up, without a new link. Another amount or
    payment method is refused until that top-up is paid, expires, or is taken back with
    'snaplii agent top-up-cancel ID'.
    """
    client, agent_token = _client_and_agent_token(ctx)
    top_up = _top_up_in_cli_terms(
        _call_as_connected_agent(lambda: client.start_top_up(agent_token, amount, payment_method)))
    what_to_do_now = _next_step_and_pay_link(top_up)
    if what_to_do_now:
        click.echo(what_to_do_now, err=True)
    deadline = time.monotonic() + timeout
    while (
        wait
        and top_up.get("status") in _TOP_UP_STATUSES_TO_POLL
        and time.monotonic() + _TOP_UP_POLL_INTERVAL_SECONDS <= deadline
    ):
        time.sleep(_TOP_UP_POLL_INTERVAL_SECONDS)
        top_up = _call_as_connected_agent(lambda: client.get_top_up(agent_token, top_up["id"]))
    print_json(_with_amount_and_cash_balance(client, agent_token, top_up))


@click.command("top-up-status")
@click.argument("top_up_id")
@click.pass_context
def agent_top_up_status_cmd(ctx, top_up_id):
    """Show a top-up as it is now: CREATED, PAID, CREDITED, EXPIRED, FAILED, REVIEW or CANCELLED.

    It asks once, so an agent can run it on a schedule. Once CREDITED, it also shows Snaplii Cash.
    """
    client, agent_token = _client_and_agent_token(ctx)
    top_up = _call_as_connected_agent(lambda: client.get_top_up(agent_token, top_up_id))
    print_json(_with_amount_and_cash_balance(client, agent_token, top_up))


@click.command("top-up-cancel")
@click.argument("top_up_id")
@click.pass_context
def agent_top_up_cancel_cmd(ctx, top_up_id):
    """Take back a top-up nobody paid yet, to ask for another amount or payment method.

    Only an unpaid top-up can be cancelled: a paid one is refused. Tell the user not to use a link
    they already got for it.
    """
    client, agent_token = _client_and_agent_token(ctx)
    cancelled_top_up = _call_as_connected_agent(lambda: client.cancel_top_up(agent_token, top_up_id))
    print_json(_with_amount_and_cash_balance(client, agent_token, cancelled_top_up))


def _next_step_and_pay_link(top_up: dict) -> str:
    """What 'snaplii agent top-up' says about a top-up it just asked for: its next_step, then the pay
    link itself where the gateway shows it, one per line."""
    lines = []
    if top_up.get("next_step"):
        lines.append(top_up["next_step"])
    if top_up.get("pay_url"):
        lines.append(f"The pay link (pay_url) to give to the user: {top_up['pay_url']}")
    return "\n".join(lines)


def _order_in_cli_terms(order: dict) -> dict:
    """The order with a next_step in this CLI's commands where the gateway's names its API calls:
    NEEDS_TOP_UP, PAYING, PAID and EXPIRED."""
    order_id, gap_cents = order.get("id"), order.get("gap_cents")
    if isinstance(gap_cents, int) and gap_cents > 0:
        gap = _dollars(gap_cents)
        short = f"Snaplii Cash is short by {gap} {order.get('currency') or ''}".rstrip() + "."
        top_up = f"'snaplii agent top-up {gap}'"
    else:
        short, top_up = "Snaplii Cash is short.", "'snaplii agent top-up AMOUNT'"
    next_step = {
        "NEEDS_TOP_UP": f"{short} Ask for a top-up of at least that much with {top_up} (the user pays on "
        "the link texted to them), or ask the user to add at least that much to their Snaplii Cash. Once "
        f"it is CREDITED, run 'snaplii agent order {order_id} --continue'. Do not buy this again with "
        "another order.",
        "PAYING": f"Snaplii is paying this order. Check it again in a few seconds with "
        f"'snaplii agent order {order_id}'. Do not order again.",
        "PAID": "Paid from Snaplii Cash; the card is in the user's Snaplii wallet, where they open it in the "
        "Snaplii app. Never show the card's code or PIN in the chat.",
        "EXPIRED": "This order waited for a top-up too long and was closed; nothing was charged. To buy it, "
        "run 'snaplii agent buy' again without --key, so it is a new order.",
    }.get(order.get("status"))
    if not next_step and _names_the_api(order.get("next_step")):
        next_step = (f"This order is {order.get('status')}. Check it with 'snaplii agent order {order_id}'; "
                     "do not order again.")
    if next_step:
        order["next_step"] = next_step
    return order


def _top_up_in_cli_terms(top_up: dict) -> dict:
    """The top-up with a next_step in this CLI's commands where the gateway's names its API calls:
    CREATED, PAID and CREDITED."""
    top_up_id, amount = top_up.get("id"), _money_of(top_up)
    wallet = "Alipay" if top_up.get("payment_method") == "alipay" else "Apple Pay or Google Pay"
    if top_up.get("texted_to"):
        link = (f"The user got a text at {top_up['texted_to']} with the link to pay {amount} with {wallet}, "
                "which adds it to their Snaplii Cash")
        link += f". It works until {top_up['expires_at']}." if top_up.get("expires_at") else "."
        if top_up.get("pay_url"):
            link += " You can also give them the link in pay_url."
    elif top_up.get("pay_url"):
        link = f"Give the user the link in pay_url: they pay {amount} there with {wallet}, which adds it to their Snaplii Cash."
    else:
        link = f"The user already has the link of this top-up of {amount}: it was in the answer that started it."
    next_step = {
        "CREATED": f"{link} Wait for them to pay: check 'snaplii agent top-up-status {top_up_id}' every "
        "few seconds until it is CREDITED, FAILED or EXPIRED. Do not start another top-up: to ask for "
        f"another amount or payment method, take this one back first with "
        f"'snaplii agent top-up-cancel {top_up_id}'.",
        "PAID": "The user paid. Snaplii is adding it to Snaplii Cash: check "
        f"'snaplii agent top-up-status {top_up_id}' again in a few seconds.",
        "CREDITED": f"{amount} is in the user's Snaplii Cash. Buy with 'snaplii agent buy', or continue the "
        "order that waited for this top-up with 'snaplii agent order ORDER_ID --continue'.",
    }.get(top_up.get("status"))
    if not next_step and _names_the_api(top_up.get("next_step")):
        next_step = (f"This top-up is {top_up.get('status')}. Check it with "
                     f"'snaplii agent top-up-status {top_up_id}' before starting another.")
    if next_step:
        top_up["next_step"] = next_step
    return top_up


def _names_the_api(next_step) -> bool:
    """Whether a next_step of the gateway's tells the agent to call its API, which an agent never does."""
    return isinstance(next_step, str) and "/api/" in next_step


def _dollars(cents: int) -> str:
    """Cents as the dollars 'snaplii agent top-up' takes, e.g. 1250 -> 12.50."""
    return f"{cents / 100:.2f}"


def _money_of(top_up: dict) -> str:
    cents = top_up.get("amount_cents")
    return format_money(cents, top_up.get("currency")) if isinstance(cents, int) else "the amount asked for"


def _with_amount_and_cash_balance(client: GatewayClient, agent_token: str, top_up: dict) -> dict:
    """The top-up with its amount as money ("CA$50.00") and, once CREDITED, the user's Snaplii Cash,
    which is one more call to the gateway (GET balance)."""
    _top_up_in_cli_terms(top_up)
    if isinstance(top_up.get("amount_cents"), int):
        top_up["amount"] = format_money(top_up["amount_cents"], top_up.get("currency"))
    if top_up.get("status") == "CREDITED":
        balance = _call_as_connected_agent(lambda: client.get_agent_balance(agent_token))
        if isinstance(balance.get("cash_cents"), int):
            top_up["cash"] = format_money(balance["cash_cents"], balance.get("currency"))
    return top_up


def _client_and_agent_token(ctx) -> tuple[GatewayClient, str]:
    store: ConfigStore = ctx.obj["config_store"]
    agent_token = store.get_agent_secret(AGENT_TOKEN)
    if not agent_token:
        raise ConnectError("This agent isn't connected by phone yet. " + CONNECT_HINT)
    return ctx.obj["client"], agent_token


def _call_as_connected_agent(request):
    try:
        return request()
    except GatewayApiError as e:
        raise_if_not_signed_in(e)
        if e.body.get("code") == "reconnect-needed":
            # The agent's token still signs the agent in, but its access to Snaplii is gone.
            raise ConnectError("This agent's access to Snaplii has ended or was never set up. " + CONNECT_HINT)
        raise


def _settled(client: GatewayClient, agent_token: str, order: dict, timeout: int) -> dict:
    """The order once Snaplii stopped paying it, or as it is when the timeout passes."""
    deadline = time.monotonic() + timeout
    while (
        order.get("status") in _ORDER_STATUSES_TO_POLL
        and time.monotonic() + _ORDER_POLL_INTERVAL_SECONDS <= deadline
    ):
        time.sleep(_ORDER_POLL_INTERVAL_SECONDS)
        order = _call_as_connected_agent(lambda: client.get_agent_order(agent_token, order["id"]))
    for name in ("amount", "gap"):
        cents = order.get(name + "_cents")
        if isinstance(cents, int):
            order[name] = format_money(cents, order.get("currency"))
    return _order_in_cli_terms(order)
