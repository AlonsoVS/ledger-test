"""SQL access. Functions run inside a session whose transaction is owned by the caller."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, select, update
from sqlalchemy.orm import Session

from ledger.db.models import CreditAccountModel, TransactionModel
from ledger.domain.balance import Balance
from ledger.domain.enums import TransactionStatus, TransactionType
from ledger.domain.money import CENT
from ledger.domain.records import Account, Transaction


def _to_account(row: CreditAccountModel) -> Account:
    return Account(
        id=row.id, customer_id=row.customer_id, created_at=row.created_at, updated_at=row.updated_at
    )


def _to_transaction(row: TransactionModel) -> Transaction:
    return Transaction(
        id=row.id,
        account_id=row.account_id,
        idempotency_key=row.idempotency_key,
        type=row.type,
        status=row.status,
        amount=row.amount,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def insert_account(session: Session, customer_id: str) -> Account:
    row = CreditAccountModel(customer_id=customer_id)
    session.add(row)
    session.flush()
    session.refresh(row)
    return _to_account(row)


def get_account(session: Session, account_id: UUID) -> Account | None:
    row = session.get(CreditAccountModel, account_id)
    return _to_account(row) if row else None


def lock_account(session: Session, account_id: UUID) -> Account | None:
    """Acquire the account's row lock until the surrounding transaction ends."""
    row = session.execute(
        select(CreditAccountModel).where(CreditAccountModel.id == account_id).with_for_update()
    ).scalar_one_or_none()
    return _to_account(row) if row else None


def find_by_idempotency_key(
    session: Session, account_id: UUID, idempotency_key: str
) -> Transaction | None:
    row = session.execute(
        select(TransactionModel).where(
            TransactionModel.account_id == account_id,
            TransactionModel.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()
    return _to_transaction(row) if row else None


def insert_transaction(
    session: Session,
    account_id: UUID,
    idempotency_key: str,
    type_: TransactionType,
    amount: Decimal,
) -> Transaction:
    row = TransactionModel(
        account_id=account_id,
        idempotency_key=idempotency_key,
        type=type_,
        status=TransactionStatus.PENDING,
        amount=amount,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return _to_transaction(row)


def get_transaction(session: Session, transaction_id: UUID) -> Transaction | None:
    row = session.get(TransactionModel, transaction_id)
    return _to_transaction(row) if row else None


def transition_if_pending(
    session: Session, transaction_id: UUID, target: TransactionStatus
) -> Transaction | None:
    """Atomically move a PENDING transaction to `target`.

    Returns None when no row matched, i.e. the transaction is missing or no longer PENDING.
    The WHERE clause makes concurrent attempts race on the row itself: exactly one wins.
    """
    row = session.execute(
        update(TransactionModel)
        .where(
            TransactionModel.id == transaction_id,
            TransactionModel.status == TransactionStatus.PENDING,
        )
        .values(status=target, updated_at=func.now())
        .returning(TransactionModel),
        execution_options={"synchronize_session": False},
    ).scalar_one_or_none()
    return _to_transaction(row) if row else None


def list_transactions(session: Session, account_id: UUID) -> list[Transaction]:
    rows = session.execute(
        select(TransactionModel)
        .where(TransactionModel.account_id == account_id)
        .order_by(TransactionModel.created_at, TransactionModel.id)
    ).scalars()
    return [_to_transaction(row) for row in rows]


def get_balance(session: Session, account_id: UUID) -> Balance:
    """Derive the balance with ONE statement so every sum shares the same snapshot."""

    def total(type_: TransactionType, status: TransactionStatus) -> ColumnElement[Decimal]:
        return func.coalesce(
            func.sum(TransactionModel.amount).filter(
                and_(TransactionModel.type == type_, TransactionModel.status == status)
            ),
            0,
        )

    types, statuses = TransactionType, TransactionStatus
    row = session.execute(
        select(
            total(types.DISBURSEMENT, statuses.COMPLETED),
            total(types.PURCHASE, statuses.COMPLETED),
            total(types.PAYMENT, statuses.COMPLETED),
            total(types.PURCHASE, statuses.PENDING),
            total(types.PAYMENT, statuses.PENDING),
        ).where(TransactionModel.account_id == account_id)
    ).one()
    granted, purchased, paid, reserved, pending_payments = (Decimal(v).quantize(CENT) for v in row)
    return Balance(
        credit_granted=granted,
        outstanding_balance=purchased - paid,
        reserved_credit=reserved,
        pending_payments=pending_payments,
    )
