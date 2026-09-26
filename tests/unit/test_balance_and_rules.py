from decimal import Decimal

import pytest

from ledger.domain.balance import Balance
from ledger.domain.enums import TransactionType
from ledger.domain.errors import InsufficientCredit, Overpayment
from ledger.domain.rules import ensure_can_create

D = Decimal


def balance(
    granted: str, outstanding: str, reserved: str = "0", pending_payments: str = "0"
) -> Balance:
    return Balance(D(granted), D(outstanding), D(reserved), D(pending_payments))


def test_available_credit_derivation() -> None:
    b = balance("1000.00", "179.50", reserved="200.00", pending_payments="50.00")
    assert b.available_credit == D("620.50")
    assert b.payable_amount == D("129.50")
    assert b.invariant_violations() == []


def test_empty_balance_is_zero_and_valid() -> None:
    b = Balance.empty()
    assert b.available_credit == 0
    assert b.invariant_violations() == []


def test_invariant_violations_are_reported() -> None:
    b = balance("100", "-10", reserved="200", pending_payments="5")
    violations = b.invariant_violations()
    assert any("negative available credit" in v for v in violations)
    assert any("negative outstanding" in v for v in violations)
    assert any("pending payments exceed" in v for v in violations)


class TestPurchaseRule:
    def test_within_available_credit(self) -> None:
        ensure_can_create(balance("1000", "900"), TransactionType.PURCHASE, D("100.00"))

    def test_exceeding_available_credit(self) -> None:
        with pytest.raises(InsufficientCredit):
            ensure_can_create(balance("1000", "900"), TransactionType.PURCHASE, D("100.01"))

    def test_reserved_credit_counts_against_availability(self) -> None:
        with pytest.raises(InsufficientCredit):
            ensure_can_create(
                balance("1000", "900", reserved="80"), TransactionType.PURCHASE, D("80.00")
            )


class TestPaymentRule:
    def test_partial_payment(self) -> None:
        ensure_can_create(balance("1000", "300"), TransactionType.PAYMENT, D("100.00"))

    def test_full_payment(self) -> None:
        ensure_can_create(balance("1000", "300"), TransactionType.PAYMENT, D("300.00"))

    def test_overpayment(self) -> None:
        with pytest.raises(Overpayment):
            ensure_can_create(balance("1000", "300"), TransactionType.PAYMENT, D("300.01"))

    def test_pending_payments_count_against_limit(self) -> None:
        with pytest.raises(Overpayment):
            ensure_can_create(
                balance("1000", "300", pending_payments="250"), TransactionType.PAYMENT, D("60.00")
            )

    def test_no_debt(self) -> None:
        with pytest.raises(Overpayment):
            ensure_can_create(balance("1000", "0"), TransactionType.PAYMENT, D("0.01"))


def test_disbursement_has_no_creation_rule() -> None:
    ensure_can_create(Balance.empty(), TransactionType.DISBURSEMENT, D("1000000.00"))
