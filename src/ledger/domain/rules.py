from decimal import Decimal

from ledger.domain.balance import Balance
from ledger.domain.enums import TransactionType
from ledger.domain.errors import InsufficientCredit, Overpayment


def ensure_can_create(balance: Balance, type_: TransactionType, amount: Decimal) -> None:
    """Business rules checked before a PENDING transaction is created.

    Callers must hold the account lock so `balance` cannot change until the insert commits.
    """
    if type_ is TransactionType.PURCHASE and amount > balance.available_credit:
        raise InsufficientCredit(amount, balance.available_credit)
    if type_ is TransactionType.PAYMENT and amount > balance.payable_amount:
        raise Overpayment(amount, balance.payable_amount)
