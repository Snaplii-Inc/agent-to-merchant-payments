"""Build the canonical payment record (from the gateway quote, never from agent
text) and the human-readable confirmation prompt derived from it."""

from __future__ import annotations

from snaplii.currency import symbol_for_currency, currency_for_country


def build_canonical_quote(quote_resp: dict, item_id: str, price: str,
                          brand_name: str | None = None,
                          country: str | None = None) -> dict:
    out: dict = {
        "item_id": str(item_id),
        "price": str(price),
        "order_amount": quote_resp.get("orderAmount"),
        "you_pay": quote_resp.get("primaryPayAmount"),
        # Currency follows the account's country (CA=CAD, US=USD); None when
        # unknown — never assume CAD. The confirmation renders it as CA$/US$.
        "currency": currency_for_country(country),
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
    # Render amounts in the account's currency (CA$/US$); bare '$' when unknown.
    sym = symbol_for_currency(canonical.get("currency"))
    parts = [
        f"Approve paying {sym}{canonical.get('you_pay')} from your Snaplii Cash "
        f"for {label} (order total {sym}{canonical.get('order_amount')})?"
    ]
    voucher = canonical.get("voucher")
    if voucher:
        parts.append(f"Voucher {voucher.get('name', '')} -{sym}{voucher.get('amount')}.")
    if canonical.get("cashback_applied"):
        parts.append(f"Cashback applied -{sym}{canonical['cashback_applied']}.")
    return " ".join(parts)
