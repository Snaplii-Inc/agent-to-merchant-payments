import click

from snaplii.client import GatewayClient
from snaplii.output import print_json


@click.command("purchase")
@click.option("--item-id", required=True, help="Item ID (e.g. CB0000000000135-CT0000000000897)")
@click.option("--price", required=True, help="Price in dollars (e.g. 50)")
@click.option("--prov", required=True, help="Region code: CA province (ON, QC, BC) or US state (NY, CA, TX)")
@click.pass_context
def purchase_cmd(ctx, item_id, price, prov):
    """Create an order and pay for a gift card.

    Always pays with SNAPLII_CREDIT, which draws from the prepaid Snaplii Cash
    balance — the only provisioned method. (Explicit SNAPLII_CASH/SNAPLII_DEBIT
    is rejected by the backend as "service not enabled", so it's not exposed.)
    """
    client: GatewayClient = ctx.obj["client"]
    resp = client.create_order_and_pay(
        item_id=item_id,
        price=price,
        location_prov=prov,
    )
    print_json(resp)
