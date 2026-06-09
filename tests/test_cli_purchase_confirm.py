from click.testing import CliRunner

from snaplii.commands.purchase import purchase_cmd
from snaplii.commands.billpay import pay_cmd


class FakeClient:
    def __init__(self):
        self.purchased = False

    def quote_order(self, **kwargs):
        return {"orderAmount": "50.00", "primaryPayAmount": "46.00"}

    def create_order_and_pay(self, **kwargs):
        self.purchased = True
        return {"orderNo": "ORD-1", "status": "SUCCESS"}


def _run(args, input_text):
    client = FakeClient()
    runner = CliRunner()
    result = runner.invoke(purchase_cmd, args, input=input_text,
                           obj={"client": client}, catch_exceptions=False)
    return result, client


def test_purchase_cancelled_when_user_says_no():
    result, client = _run(["--item-id", "I-1", "--price", "50", "--prov", "ON"], "n\n")
    assert client.purchased is False
    assert "cancelled" in result.output.lower()


def test_purchase_proceeds_when_user_says_yes():
    result, client = _run(["--item-id", "I-1", "--price", "50", "--prov", "ON"], "y\n")
    assert client.purchased is True
    assert "ORD-1" in result.output


def test_purchase_yes_flag_skips_prompt():
    result, client = _run(["--item-id", "I-1", "--price", "50", "--prov", "ON", "--yes"], "")
    assert client.purchased is True


class FakeBillPayClient:
    def __init__(self):
        self.paid = False

    def billpay_quote(self, **kwargs):
        return {"orderAmount": "30.00", "primaryPayAmount": "30.00"}

    def billpay_create_and_pay(self, **kwargs):
        self.paid = True
        return {"orderNo": "BP-1", "paymentNo": "PAY-1", "orderStatus": "SUCCESS"}


def _run_pay(args, input_text):
    client = FakeBillPayClient()
    runner = CliRunner()
    result = runner.invoke(pay_cmd, args, input=input_text,
                           obj={"client": client}, catch_exceptions=False)
    return result, client


def test_billpay_cancelled_when_user_says_no():
    result, client = _run_pay(
        ["--pay-code", "PC-1", "--price", "30", "--prov", "ON"], "n\n")
    assert client.paid is False
    assert "cancelled" in result.output.lower()


def test_billpay_yes_flag_skips_prompt():
    result, client = _run_pay(
        ["--pay-code", "PC-1", "--price", "30", "--prov", "ON", "--yes"], "")
    assert client.paid is True
    assert "BP-1" in result.output
