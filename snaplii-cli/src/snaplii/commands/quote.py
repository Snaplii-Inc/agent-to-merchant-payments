import click

from snaplii.client import GatewayClient
from snaplii.output import print_json


@click.command("quote")
@click.option("--item-id", required=True, help="Item ID: {brandId}-{templateId}")
@click.option("--price", required=True, help="Price in dollars")
@click.option("--payment-method", default="SNAPLII_CREDIT", help="Payment method")
@click.option("--voucher", default="BEST_FIT", type=click.Choice(["BEST_FIT", "USE", "NOT_USE"]),
              help="Voucher option: BEST_FIT (auto-apply best), USE, NOT_USE")
@click.option("--cashback", default="USE", type=click.Choice(["USE", "NOT_USE"]),
              help="Cashback option: USE or NOT_USE")
@click.option("--voucher-id", default=None, help="Specify a voucher ID to apply")
@click.pass_context
def quote_cmd(ctx, item_id, price, payment_method, voucher, cashback, voucher_id):
    """Get a price quote before purchasing.

    Shows the order total, voucher discount, cashback applied,
    and the actual amount you'll pay.
    """
    client: GatewayClient = ctx.obj["client"]
    resp = client.quote_order(
        item_id=item_id,
        price=price,
        payment_method=payment_method,
        voucher_option=voucher,
        cashback_option=cashback,
        specified_voucher=voucher_id,
    )

    # Format a clean summary
    summary = {
        "order_amount": resp.get("orderAmount"),
        "you_pay": resp.get("primaryPayAmount"),
    }

    voucher_amount = resp.get("voucherAmount")
    if voucher_amount:
        summary["voucher"] = {
            "name": resp.get("voucherName"),
            "discount": f"-${voucher_amount}",
        }

    cashback_amount = resp.get("cashbackUseAmount")
    if cashback_amount:
        summary["snaplii_cash_applied"] = f"-${cashback_amount}"

    subsidy_amount = resp.get("subsidyAmount")
    if subsidy_amount:
        summary["subsidy"] = f"-${subsidy_amount}"

    commission = resp.get("commissionAmount")
    if commission:
        summary["commission"] = f"${commission}"

    # Warn if Snaplii Cash doesn't fully cover the order
    try:
        you_pay = float(resp.get("primaryPayAmount", "0"))
        if you_pay > 0:
            summary["warning"] = (
                f"Snaplii Cash does not fully cover this order. "
                f"${you_pay:.2f} remaining requires another payment method, "
                f"which is not supported via CLI. Please top up your Snaplii Cash "
                f"in the app before purchasing."
            )
    except (ValueError, TypeError):
        pass

    print_json(summary)
