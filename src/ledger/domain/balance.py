from dataclasses import dataclass
from decimal import Decimal

from ledger.domain.money import ZERO


@dataclass(frozen=True, slots=True)
class Balance:
    """Account state derived from the ledger. Never stored."""

    credit_granted: Decimal
    outstanding_balance: Decimal
    reserved_credit: Decimal  # credit reserved by PENDING purchases
    pending_payments: Decimal  # payment capacity reserved by PENDING payments

    @classmethod
    def empty(cls) -> "Balance":
        return cls(ZERO, ZERO, ZERO, ZERO)

    @property
    def available_credit(self) -> Decimal:
        return self.credit_granted - self.outstanding_balance - self.reserved_credit

    @property
    def payment_capacity(self) -> Decimal:
        """Outstanding debt not yet claimed by a PENDING payment.

        A pending payment reserves capacity at creation; completing it lowers outstanding and
        pending_payments by the same amount, so the reserved capacity stays consumed.
        """
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
        if self.payment_capacity < 0:
            violations.append(f"negative payment capacity: {self.payment_capacity}")
        return violations
