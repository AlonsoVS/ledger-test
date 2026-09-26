from decimal import Decimal

import pytest

from ledger.domain.errors import InvalidAmount
from ledger.domain.money import parse_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("100", Decimal("100.00")),
        ("100.5", Decimal("100.50")),
        ("100.50", Decimal("100.50")),
        ("100.500", Decimal("100.50")),  # trailing zeros carry no extra precision
        ("0.01", Decimal("0.01")),
        (Decimal("7.25"), Decimal("7.25")),
        (42, Decimal("42.00")),
        ("99999999999999999.99", Decimal("99999999999999999.99")),
    ],
)
def test_valid_amounts_are_normalised_to_cents(raw: Decimal | str | int, expected: Decimal) -> None:
    parsed = parse_amount(raw)
    assert parsed == expected
    assert parsed.as_tuple().exponent == -2


@pytest.mark.parametrize(
    "raw",
    [
        "0",
        "0.00",
        "-100.00",
        "10.005",  # rejected, not rounded to 10.01
        "0.001",
        "100000000000000000.00",  # 18 integer digits overflow NUMERIC(19,2)
        "NaN",
        "Infinity",
        "abc",
        "",
    ],
)
def test_invalid_amounts_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidAmount):
        parse_amount(raw)


@pytest.mark.parametrize("raw", [10.1, 1.0, True])
def test_floats_and_bools_are_rejected(raw: object) -> None:
    with pytest.raises(InvalidAmount):
        parse_amount(raw)  # type: ignore[arg-type]


def test_decimal_arithmetic_is_exact() -> None:
    total = sum((parse_amount(a) for a in ("0.10", "0.20", "0.70")), Decimal("0.00"))
    assert total == Decimal("1.00")
