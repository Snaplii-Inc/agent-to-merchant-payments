import click

from snaplii.client import GatewayClient
from snaplii.output import print_json


@click.command("purchase")
@click.option("--item-id", required=True,
              help="Exactly {cardBrandId}-{cardTemplateId}, copied verbatim from the item_id in `snaplii browse brand` denominations (e.g. CB00000000000086-CT000000003618)")
@click.option("--price", required=True, help="Price in dollars (e.g. 50)")
@click.pass_context
def purchase_cmd(ctx, item_id, price):
    """Buy a gift card from the prepaid Snaplii Cash balance.

    The charge always comes from Snaplii Cash (SNAPLII_CREDIT); there is no
    method to choose. It happens as soon as the command runs, within the per-key
    daily limit set in the app. Use `snaplii quote` first to see the exact cost.
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
