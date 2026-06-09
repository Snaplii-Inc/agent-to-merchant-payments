from snaplii.security.canonical import build_canonical_quote, build_confirmation_message


GATEWAY_QUOTE = {
    "orderAmount": "50.00",
    "primaryPayAmount": "46.00",
    "voucherAmount": "2.00",
    "voucherName": "Welcome $2",
    "cashbackUseAmount": "2.00",
}


def test_build_canonical_extracts_fields():
    c = build_canonical_quote(GATEWAY_QUOTE, "ITEM-1", "50", brand_name="DoorDash")
    assert c["item_id"] == "ITEM-1"
    assert c["price"] == "50"
    assert c["order_amount"] == "50.00"
    assert c["you_pay"] == "46.00"
    assert c["brand"] == "DoorDash"
    assert c["voucher"] == {"name": "Welcome $2", "amount": "2.00"}
    assert c["cashback_applied"] == "2.00"


def test_build_canonical_omits_absent_optionals():
    c = build_canonical_quote({"orderAmount": "25", "primaryPayAmount": "25"}, "ITEM-2", "25")
    assert "voucher" not in c
    assert "cashback_applied" not in c
    assert "brand" not in c


def test_confirmation_message_mentions_amount_and_brand():
    c = build_canonical_quote(GATEWAY_QUOTE, "ITEM-1", "50", brand_name="DoorDash")
    msg = build_confirmation_message(c)
    assert "46.00" in msg
    assert "DoorDash" in msg
    assert "Snaplii Cash" in msg


def test_confirmation_message_without_brand_uses_item_id():
    c = build_canonical_quote({"orderAmount": "25", "primaryPayAmount": "25"}, "ITEM-2", "25")
    msg = build_confirmation_message(c)
    assert "ITEM-2" in msg
