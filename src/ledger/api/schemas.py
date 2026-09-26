"""HTTP schemas. Amounts travel as JSON strings; JSON numbers are rejected (no float path)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ledger.domain.enums import TransactionStatus, TransactionType
from ledger.domain.records import Account, Transaction
from ledger.service import AccountView


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: Annotated[StrictStr, Field(min_length=1, max_length=64)]


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TransactionType
    # StrictStr: a JSON number is a validation error rather than being coerced.
    amount: Annotated[StrictStr, Field(examples=["100.00"])]


class BalanceOut(BaseModel):
    # Pydantic serialises Decimal as a JSON string, preserving exact values.
    credit_granted: Decimal
    outstanding_balance: Decimal
    reserved_credit: Decimal
    pending_payments: Decimal
    available_credit: Decimal
    payment_capacity: Decimal


class AccountOut(BaseModel):
    id: UUID
    customer_id: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, account: Account) -> "AccountOut":
        return cls(
            id=account.id,
            customer_id=account.customer_id,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )


class AccountWithBalanceOut(AccountOut):
    balance: BalanceOut

    @classmethod
    def from_view(cls, view: AccountView) -> "AccountWithBalanceOut":
        b = view.balance
        return cls(
            **AccountOut.from_record(view.account).model_dump(),
            balance=BalanceOut(
                credit_granted=b.credit_granted,
                outstanding_balance=b.outstanding_balance,
                reserved_credit=b.reserved_credit,
                pending_payments=b.pending_payments,
                available_credit=b.available_credit,
                payment_capacity=b.payment_capacity,
            ),
        )


class TransactionOut(BaseModel):
    id: UUID
    account_id: UUID
    idempotency_key: str
    type: TransactionType
    status: TransactionStatus
    amount: Decimal
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, tx: Transaction) -> "TransactionOut":
        return cls(
            id=tx.id,
            account_id=tx.account_id,
            idempotency_key=tx.idempotency_key,
            type=tx.type,
            status=tx.status,
            amount=tx.amount,
            created_at=tx.created_at,
            updated_at=tx.updated_at,
        )


class ErrorOut(BaseModel):
    code: str
    message: str
