"""Exact monetary amounts.

Amounts are `Decimal` values with at most two decimal places that fit in
NUMERIC(19,2). Invalid input is rejected, never rounded.
"""

from decimal import Decimal, InvalidOperation

from ledger.domain.errors import InvalidAmount

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
MAX_INTEGER_DIGITS = 17  # NUMERIC(19,2): 19 digits of precision, 2 of them decimals


def parse_amount(value: Decimal | str | int) -> Decimal:
    """Validate a transaction amount and normalise it to two decimal places."""
    # bool is a subclass of int, and floats are exactly what we must never accept.
    if isinstance(value, bool | float) or not isinstance(value, Decimal | str | int):
        raise InvalidAmount(f"Unsupported amount type: {type(value).__name__}")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(value)
    except InvalidOperation:
        raise InvalidAmount(f"Amount {value!r} is not a decimal number") from None

    if not amount.is_finite():
        raise InvalidAmount(f"Amount {value!r} must be finite")
    if amount <= 0:
        raise InvalidAmount(f"Amount {value!r} must be greater than zero")
    if amount.adjusted() + 1 > MAX_INTEGER_DIGITS:
        raise InvalidAmount(f"Amount {value!r} exceeds {MAX_INTEGER_DIGITS} integer digits")

    normalised = amount.quantize(CENT)
    if normalised != amount:
        raise InvalidAmount(f"Amount {value!r} has more than two decimal places")
    return normalised
