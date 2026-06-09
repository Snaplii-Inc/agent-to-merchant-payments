import click

from snaplii.client import GatewayClient
from snaplii.output import print_json
from snaplii.security.canonical import build_canonical_quote, build_confirmation_message


@click.command("purchase")
@click.option("--item-id", required=True, help="Item ID (e.g. CB0000000000135-CT0000000000897)")
@click.option("--price", required=True, help="Price in dollars (e.g. 50)")
@click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt (for scripts).")
@click.pass_context
def purchase_cmd(ctx, item_id, price, yes):
    """Create an order and pay for a gift card.

    Always pays with SNAPLII_CREDIT, which draws from the prepaid Snaplii Cash
    balance — the only provisioned method. (Explicit SNAPLII_CASH/SNAPLII_DEBIT
    is rejected by the backend as "service not enabled", so it's not exposed.)
    Shows the exact amount from a fresh quote and asks for confirmation before
    charging, unless --yes is passed.
    """
    client: GatewayClient = ctx.obj["client"]

    if not yes:
        quote = client.quote_order(item_id=item_id, price=price)
        canonical = build_canonical_quote(quote, item_id, price)
        click.echo(build_confirmation_message(canonical), err=True)
        if not click.confirm("Proceed with this purchase?", default=False):
            print_json({"status": "cancelled", "message": "Purchase cancelled. No charge was made."})
            return

    resp = client.create_order_and_pay(
        item_id=item_id,
        price=price,
    )
    print_json(resp)
