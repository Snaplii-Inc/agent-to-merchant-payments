import click

from snaplii.client import GatewayClient
from snaplii.output import print_json


@click.command("purchase")
@click.option("--item-id", required=True,
              help="Exactly {cardBrandId}-{cardTemplateId}, copied verbatim from the item_id in `snaplii browse brand` denominations (e.g. CB00000000000086-CT000000003618)")
@click.option("--price", required=True, help="Price in dollars (e.g. 50)")
@click.option("--voucher", default="BEST_FIT", type=click.Choice(["BEST_FIT", "USE", "NOT_USE"]),
              help="Voucher option; pass the same value you quoted with")
@click.option("--cashback", default="USE", type=click.Choice(["USE", "NOT_USE"]),
              help="Cashback option; pass the same value you quoted with")
@click.option("--voucher-id", default=None, help="Specific voucher ID; pass the same value you quoted with")
@click.pass_context
def purchase_cmd(ctx, item_id, price, voucher, cashback, voucher_id):
    """Create an order and pay for a gift card.

    Always pays with SNAPLII_CREDIT, which draws from the prepaid Snaplii Cash
    balance; there is no method to choose. The charge happens as soon as the
    command runs, within the per-key daily limit set in the app. Use
    `snaplii quote` first to see the exact cost, and pass the same --voucher,
    --cashback and --voucher-id here so the charge matches the quote.
    """
    client: GatewayClient = ctx.obj["client"]
    # Hard stop before charging: reject amounts outside the brand's denomination
    # range so Snaplii Cash isn't debited for a card that will fail and refund.
    client.validate_amount(item_id, price)
    resp = client.create_order_and_pay(
        item_id=item_id,
        price=price,
        voucher_option=voucher,
        cashback_option=cashback,
        specified_voucher=voucher_id,
    )
    print_json(resp)
