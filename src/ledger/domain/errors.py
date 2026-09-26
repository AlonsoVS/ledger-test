from decimal import Decimal
from uuid import UUID

from ledger.domain.enums import TransactionStatus


class LedgerError(Exception):
    """Base class for domain errors. `code` is a stable, machine-readable identifier."""

    code = "LEDGER_ERROR"


class InvalidRequest(LedgerError):
    code = "INVALID_REQUEST"


class InvalidAmount(LedgerError):
    code = "INVALID_AMOUNT"


class AccountNotFound(LedgerError):
    code = "ACCOUNT_NOT_FOUND"

    def __init__(self, account_id: UUID) -> None:
        super().__init__(f"Credit account {account_id} not found")
        self.account_id = account_id


class TransactionNotFound(LedgerError):
    code = "TRANSACTION_NOT_FOUND"

    def __init__(self, transaction_id: UUID) -> None:
        super().__init__(f"Transaction {transaction_id} not found")
        self.transaction_id = transaction_id


class InsufficientCredit(LedgerError):
    code = "INSUFFICIENT_CREDIT"

    def __init__(self, requested: Decimal, available: Decimal) -> None:
        super().__init__(f"Purchase of {requested} exceeds available credit of {available}")
        self.requested = requested
        self.available = available


class Overpayment(LedgerError):
    code = "OVERPAYMENT"

    def __init__(self, requested: Decimal, payable: Decimal) -> None:
        super().__init__(f"Payment of {requested} exceeds payable amount of {payable}")
        self.requested = requested
        self.payable = payable


class IdempotencyConflict(LedgerError):
    code = "IDEMPOTENCY_CONFLICT"

    def __init__(self, idempotency_key: str) -> None:
        super().__init__(
            f"Idempotency key {idempotency_key!r} was already used with different parameters"
        )
        self.idempotency_key = idempotency_key


class InvalidStateTransition(LedgerError):
    code = "INVALID_STATE_TRANSITION"

    def __init__(
        self, transaction_id: UUID, current: TransactionStatus, target: TransactionStatus
    ) -> None:
        super().__init__(
            f"Transaction {transaction_id} cannot transition from {current} to {target}"
        )
        self.transaction_id = transaction_id
        self.current = current
        self.target = target
