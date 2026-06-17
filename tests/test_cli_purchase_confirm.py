"""CLI purchase / bill-pay now charge directly — no per-transaction confirmation
prompt (consent is the per-key daily limit set in the app)."""

from click.testing import CliRunner

from snaplii.commands.purchase import purchase_cmd
from snaplii.commands.billpay import pay_cmd


class _FakeStore:
    def get(self, key, default=None):
        return default


class FakeClient:
    def __init__(self):
        self.purchased = False

    def create_order_and_pay(self, **kwargs):
        self.purchased = True
        return {"orderNo": "ORD-1", "status": "SUCCESS"}


def _run(args):
    client = FakeClient()
    result = CliRunner().invoke(purchase_cmd, args,
                                obj={"client": client, "config_store": _FakeStore()},
                                catch_exceptions=False)
    return result, client


def test_purchase_charges_without_prompt():
    result, client = _run(["--item-id", "I-1", "--price", "50"])
    assert client.purchased is True
    assert "ORD-1" in result.output


def test_purchase_has_no_yes_flag():
    # --yes was the confirmation-skip flag; it no longer exists.
    result, _ = _run(["--item-id", "I-1", "--price", "50", "--yes"])
    assert result.exit_code != 0
    assert "no such option" in result.output.lower()


class FakeBillPayClient:
    def __init__(self):
        self.paid = False

    def billpay_create_and_pay(self, **kwargs):
        self.paid = True
        return {"orderNo": "BP-1", "paymentNo": "PAY-1", "orderStatus": "SUCCESS"}


def _run_pay(args):
    client = FakeBillPayClient()
    result = CliRunner().invoke(pay_cmd, args,
                                obj={"client": client, "config_store": _FakeStore()},
                                catch_exceptions=False)
    return result, client


def test_billpay_pays_without_prompt():
    result, client = _run_pay(["--pay-code", "PC-1", "--price", "30"])
    assert client.paid is True
    assert "BP-1" in result.output
