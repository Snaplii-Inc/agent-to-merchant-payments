import click

from snaplii.client import GatewayClient
from snaplii.output import print_json


@click.command("balance")
@click.pass_context
def balance_cmd(ctx):
    """Show your spendable Snaplii Cash / cashback balance.

    This is the real, current balance pulled from your account — the same
    pool that pays for gift cards and bills. Run this before quoting or
    buying so you know up front whether the order is covered.
    """
    client: GatewayClient = ctx.obj["client"]
    resp = client.get_balance()

    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    balance = data.get("balance") if isinstance(data, dict) else None

    summary = {
        "balance": balance,
        "currency": "CAD",
        "spendable": True,
    }

    # First-time users often have $0 until they top up. Don't dead-end them —
    # hand the agent a warm, actionable next step instead of just a bare number.
    try:
        if balance is not None and float(balance) <= 0:
            summary["note"] = (
                "Balance is $0 — this is normal for a new account. To buy gift cards "
                "or pay bills, add funds in the Snaplii app (Wallet -> Add Cash / Top Up), "
                "then re-run 'snaplii balance' to confirm. Nothing else to set up."
            )
    except (ValueError, TypeError):
        pass

    print_json(summary)
