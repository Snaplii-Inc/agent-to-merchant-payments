"""Single source of truth for the account's currency.

Snaplii Cash is held in the account's local currency. The backend doesn't
return it, so it follows the account country (CA/US) cached at login. Never
assume CAD — when the country is unknown, callers fall back to a bare '$'.
"""

from __future__ import annotations

_CURRENCY_BY_COUNTRY = {"CA": "CAD", "US": "USD"}
_SYMBOL_BY_CURRENCY = {"CAD": "CA$", "USD": "US$"}


def currency_for_country(country: str | None) -> str | None:
    """Map an account country (CA/US) to its currency code (CAD/USD).

    Returns None when the country is unknown — callers must not guess.
    """
    return _CURRENCY_BY_COUNTRY.get((country or "").strip().upper())


def symbol_for_currency(currency: str | None) -> str:
    """Display symbol for a currency code (CAD -> CA$, USD -> US$).

    Falls back to a bare '$' for an unknown/None currency — never assume.
    """
    return _SYMBOL_BY_CURRENCY.get((currency or "").strip().upper(), "$")


def symbol_for_country(country: str | None) -> str:
    """Convenience: currency symbol for an account country, '$' when unknown."""
    return symbol_for_currency(currency_for_country(country))
