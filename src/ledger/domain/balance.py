from dataclasses import dataclass
from decimal import Decimal

from ledger.domain.money import ZERO


@dataclass(frozen=True, slots=True)
class Balance:
    """Account state derived from the ledger. Never stored."""

    credit_granted: Decimal
    outstanding_balance: Decimal
    reserved_credit: Decimal
    pending_payments: Decimal

    @classmethod
    def empty(cls) -> "Balance":
        return cls(ZERO, ZERO, ZERO, ZERO)

    @property
    def available_credit(self) -> Decimal:
        return self.credit_granted - self.outstanding_balance - self.reserved_credit

    @property
    def payable_amount(self) -> Decimal:
        """How much can still be paid without the account ever going into credit."""
        return self.outstanding_balance - self.pending_payments

    def invariant_violations(self) -> list[str]:
        violations = []
        # Conservation holds by construction of `available_credit`; it is checked anyway so
        # that the invariant is stated explicitly wherever balances are verified.
        allocated = self.available_credit + self.outstanding_balance + self.reserved_credit
        if self.credit_granted != allocated:
            violations.append(f"credit conservation: {self.credit_granted} != {allocated}")
        if self.available_credit < 0:
            violations.append(f"negative available credit: {self.available_credit}")
        if self.outstanding_balance < 0:
            violations.append(f"negative outstanding balance: {self.outstanding_balance}")
        if self.payable_amount < 0:
            violations.append(f"pending payments exceed outstanding: {self.payable_amount}")
        return violations
