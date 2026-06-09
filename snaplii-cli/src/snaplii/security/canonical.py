"""Build the canonical payment record (from the gateway quote, never from agent
text) and the human-readable confirmation prompt derived from it."""

from __future__ import annotations


def build_canonical_quote(quote_resp: dict, item_id: str, price: str,
                          brand_name: str | None = None) -> dict:
    out: dict = {
        "item_id": str(item_id),
        "price": str(price),
        "order_amount": quote_resp.get("orderAmount"),
        "you_pay": quote_resp.get("primaryPayAmount"),
        "currency": "CAD",
    }
    if brand_name:
        out["brand"] = brand_name
    if quote_resp.get("voucherAmount"):
        out["voucher"] = {
            "name": quote_resp.get("voucherName"),
            "amount": quote_resp.get("voucherAmount"),
        }
    if quote_resp.get("cashbackUseAmount"):
        out["cashback_applied"] = quote_resp.get("cashbackUseAmount")
    return out


def build_confirmation_message(canonical: dict) -> str:
    label = canonical.get("brand") or canonical.get("item_id")
    parts = [
        f"Approve paying ${canonical.get('you_pay')} from your Snaplii Cash "
        f"for {label} (order total ${canonical.get('order_amount')})?"
    ]
    voucher = canonical.get("voucher")
    if voucher:
        parts.append(f"Voucher {voucher.get('name', '')} -${voucher.get('amount')}.")
    if canonical.get("cashback_applied"):
        parts.append(f"Cashback applied -${canonical['cashback_applied']}.")
    return " ".join(parts)
