import click

from snaplii.client import GatewayClient
from snaplii.output import print_json


@click.group("billpay")
@click.pass_context
def billpay_group(ctx):
    """Bill Pay — pay utility bills, telecoms, and more."""
    pass


@billpay_group.command("payees")
@click.pass_context
def payees_cmd(ctx):
    """List available billers/payees."""
    client: GatewayClient = ctx.obj["client"]
    resp = client.billpay_payee_list()
    data = resp.get("data", [])
    summary = []
    for p in data:
        summary.append({
            "payeeCode": p.get("payeeCode"),
            "name": p.get("payeeNameEn") or p.get("payeeNameBillPay"),
            "category": p.get("payeeMcc"),
        })
    print_json({"total": len(summary), "payees": summary})


@billpay_group.command("detail")
@click.option("--payee-code", required=True, help="Payee code from 'billpay payees'")
@click.pass_context
def detail_cmd(ctx, payee_code):
    """Get payee details and account validation rules."""
    client: GatewayClient = ctx.obj["client"]
    resp = client.billpay_payee_detail(payee_code)
    summary = {
        "payeeCode": resp.get("payeeCode"),
        "name": resp.get("payeeNameBillPay") or resp.get("payeeNameEn"),
        "accountLabel": resp.get("accountTypeEn"),
        "accountRegex": resp.get("accountRegex"),
        "tips": resp.get("payeeTipsEn"),
    }
    print_json(summary)


@billpay_group.command("history")
@click.option("--payee-code", required=True, help="Payee code")
@click.pass_context
def history_cmd(ctx, payee_code):
    """Get previous bill pay info for autofill."""
    client: GatewayClient = ctx.obj["client"]
    resp = client.billpay_history(payee_code)
    print_json(resp)


@billpay_group.command("save")
@click.option("--payee-code", required=True, help="Payee code")
@click.option("--first-name", required=True, help="Payer first name")
@click.option("--last-name", required=True, help="Payer last name")
@click.option("--amount", required=True, help="Payment amount")
@click.option("--account", required=True, help="Account number at the biller")
@click.option("--phone", default=None, help="Payer phone (optional)")
@click.option("--email", default=None, help="Payer email (optional)")
@click.option("--remark", default=None, help="Memo (optional)")
@click.pass_context
def save_cmd(ctx, payee_code, first_name, last_name, amount, account, phone, email, remark):
    """Save bill pay instruction and get a payCode for checkout."""
    client: GatewayClient = ctx.obj["client"]
    resp = client.billpay_save(
        payee_code=payee_code,
        first_name=first_name,
        last_name=last_name,
        amount=amount,
        account=account,
        phone=phone,
        email=email,
        remark=remark,
    )
    print_json({
        "payCode": resp.get("payCode"),
        "fee": resp.get("payFeeAmount"),
        "status": "saved",
    })


@billpay_group.command("vouchers")
@click.option("--pay-code", required=True, help="payCode from 'billpay save'")
@click.option("--price", required=True, help="Bill amount")
@click.pass_context
def vouchers_cmd(ctx, pay_code, price):
    """List available vouchers for this bill payment."""
    client: GatewayClient = ctx.obj["client"]
    resp = client.billpay_vouchers(pay_code, price)
    vouchers = resp.get("rec", [])
    summary = []
    for v in vouchers:
        summary.append({
            "voucherId": v.get("voucherId"),
            "name": v.get("voucherName"),
            "value": v.get("voucherPrice"),
            "expires": v.get("expiredTime"),
        })
    print_json({"vouchers": summary})


@billpay_group.command("quote")
@click.option("--pay-code", required=True, help="payCode from 'billpay save'")
@click.option("--price", required=True, help="Bill amount")
@click.option("--voucher-id", default=None, help="Specific voucher ID to apply")
@click.pass_context
def quote_cmd(ctx, pay_code, price, voucher_id):
    """Get a price quote before paying the bill."""
    client: GatewayClient = ctx.obj["client"]
    resp = client.billpay_quote(
        pay_code=pay_code,
        price=price,
        specified_voucher=voucher_id,
    )
    summary = {
        "order_amount": resp.get("orderAmount"),
        "you_pay": resp.get("primaryPayAmount"),
        "commission": resp.get("commissionAmount"),
    }
    if resp.get("voucherAmount"):
        summary["voucher"] = {
            "name": resp.get("voucherName"),
            "discount": f"-${resp['voucherAmount']}",
        }
    if resp.get("cashbackUseAmount"):
        summary["snaplii_cash_applied"] = f"-${resp['cashbackUseAmount']}"
    try:
        you_pay = float(resp.get("primaryPayAmount", "0"))
        if you_pay > 0:
            summary["warning"] = (
                f"Snaplii Cash does not fully cover this bill. ${you_pay:.2f} remaining "
                f"requires another payment method, which is not supported via CLI. "
                f"Please top up your Snaplii Cash in the app before paying."
            )
    except (ValueError, TypeError):
        pass
    print_json(summary)


@billpay_group.command("pay")
@click.option("--pay-code", required=True, help="payCode from 'billpay save'")
@click.option("--price", required=True, help="Bill amount")
@click.option("--voucher-id", default=None, help="Specific voucher ID to apply")
@click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt (for scripts).")
@click.pass_context
def pay_cmd(ctx, pay_code, price, voucher_id, yes):
    """Pay the bill from Snaplii Cash balance."""
    client: GatewayClient = ctx.obj["client"]
    if not yes:
        quote = client.billpay_quote(pay_code=pay_code, price=price, specified_voucher=voucher_id)
        from snaplii.security.canonical import build_canonical_quote, build_confirmation_message
        canonical = build_canonical_quote(quote, pay_code, price)
        canonical["brand"] = "bill payment"
        click.echo(build_confirmation_message(canonical), err=True)
        if not click.confirm("Proceed with this bill payment?", default=False):
            print_json({"status": "cancelled", "message": "Bill payment cancelled. No charge was made."})
            return
    resp = client.billpay_create_and_pay(
        pay_code=pay_code,
        price=price,
        specified_voucher=voucher_id,
    )
    status = resp.get("orderStatus", "")
    summary = {
        "orderNo": resp.get("orderNo"),
        "paymentNo": resp.get("paymentNo"),
        "orderStatus": status,
    }
    if status in ("SUCCESS", "WAIT_DELIVER"):
        summary["result"] = "Bill paid successfully from Snaplii Cash."
    elif resp.get("h5PayUrl"):
        # Fallback: Snaplii Cash insufficient, balance must be topped up externally
        summary["warning"] = "Snaplii Cash did not fully cover the bill. Top up in the Snaplii app and retry."
        summary["paypal_approval_url"] = resp["h5PayUrl"]
    print_json(summary)


@billpay_group.command("result")
@click.option("--payment-no", required=True, help="paymentNo from 'billpay pay'")
@click.pass_context
def result_cmd(ctx, payment_no):
    """Check bill pay payment result."""
    client: GatewayClient = ctx.obj["client"]
    resp = client.billpay_pay_result(payment_no)
    pay_sts = resp.get("paySts", "")
    status_map = {"0": "SUCCESS", "1": "FAILED", "3": "PROCESSING"}
    summary = {"status": status_map.get(pay_sts, pay_sts)}
    if pay_sts == "1":
        summary["error"] = resp.get("payErrMsg", resp.get("payErrTitle", "Payment failed"))
    if pay_sts == "3":
        summary["next_step"] = "Payment is still processing. Wait a moment and check again."
    print_json(summary)
