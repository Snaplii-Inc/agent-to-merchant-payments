from click.testing import CliRunner

from snaplii.commands.purchase import purchase_cmd, _brand_name
from snaplii.commands.billpay import pay_cmd


class _FakeStore:
    """Minimal config store for the CLI context (only `country` is read here)."""

    def __init__(self, country=None):
        self._country = country

    def get(self, key, default=None):
        return self._country if key == "country" else default


class FakeClient:
    def __init__(self):
        self.purchased = False

    def quote_order(self, **kwargs):
        return {"orderAmount": "50.00", "primaryPayAmount": "46.00"}

    def get_card_brand_by_id(self, brand_id):
        # Gateway carries the brand name at data.desc.name.
        return {"data": {"cardBrandId": brand_id, "desc": {"name": "Amazon"}}}

    def create_order_and_pay(self, **kwargs):
        self.purchased = True
        return {"orderNo": "ORD-1", "status": "SUCCESS"}


def test_brand_name_resolved_from_detail():
    assert _brand_name(FakeClient(), "CB82-CT1") == "Amazon"


def test_brand_name_none_on_lookup_failure():
    class Boom:
        def get_card_brand_by_id(self, brand_id):
            raise RuntimeError("404 not found")

    class NoMethod:
        pass

    assert _brand_name(Boom(), "CB82-CT1") is None       # error swallowed -> fall back
    assert _brand_name(NoMethod(), "CB82-CT1") is None   # missing method -> fall back


def test_brand_name_none_when_field_absent():
    class NoDesc:
        def get_card_brand_by_id(self, brand_id):
            return {"data": {"cardBrandId": brand_id}}  # no desc.name

    assert _brand_name(NoDesc(), "CB82-CT1") is None


def _run(args, input_text, country=None):
    client = FakeClient()
    runner = CliRunner()
    result = runner.invoke(purchase_cmd, args, input=input_text,
                           obj={"client": client, "config_store": _FakeStore(country)},
                           catch_exceptions=False)
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


def _run_pay(args, input_text, country=None):
    client = FakeBillPayClient()
    runner = CliRunner()
    result = runner.invoke(pay_cmd, args, input=input_text,
                           obj={"client": client, "config_store": _FakeStore(country)},
                           catch_exceptions=False)
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
