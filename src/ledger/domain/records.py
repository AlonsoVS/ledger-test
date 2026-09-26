from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from ledger.domain.enums import TransactionStatus, TransactionType


@dataclass(frozen=True, slots=True)
class Account:
    id: UUID
    customer_id: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Transaction:
    id: UUID
    account_id: UUID
    idempotency_key: str
    type: TransactionType
    status: TransactionStatus
    amount: Decimal
    created_at: datetime
    updated_at: datetime

    def matches(self, type_: TransactionType, amount: Decimal) -> bool:
        """Whether a replayed request describes the same operation as this transaction."""
        return self.type is type_ and self.amount == amount
