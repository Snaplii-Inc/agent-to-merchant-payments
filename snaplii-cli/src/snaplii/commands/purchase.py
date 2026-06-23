import click

from snaplii.client import GatewayClient
from snaplii.output import print_json


@click.command("purchase")
@click.option("--item-id", required=True, help="Item ID (e.g. CB0000000000135-CT0000000000897)")
@click.option("--price", required=True, help="Price in dollars (e.g. 50)")
@click.pass_context
def purchase_cmd(ctx, item_id, price):
    """Create an order and pay for a gift card.

    Always pays with SNAPLII_CREDIT, which draws from the prepaid Snaplii Cash
    balance — the only provisioned method. (Explicit SNAPLII_CASH/SNAPLII_DEBIT
    is rejected by the backend as "service not enabled", so it's not exposed.)
    Spends within the per-key daily limit set in the app; no per-transaction
    confirmation. Use `snaplii quote` first if you want to see the exact cost.
    """
    client: GatewayClient = ctx.obj["client"]
    # Hard stop before charging: reject amounts outside the brand's denomination
    # range so Snaplii Cash isn't debited for a card that will fail and refund.
    client.validate_amount(item_id, price)
    resp = client.create_order_and_pay(
        item_id=item_id,
        price=price,
    )
    print_json(resp)
