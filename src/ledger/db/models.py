import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ledger.domain.enums import TransactionStatus, TransactionType


class Base(DeclarativeBase):
    pass


class CreditAccountModel(Base):
    """Concurrency boundary for transaction creation. Deliberately holds no balance."""

    __tablename__ = "credit_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TransactionModel(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "idempotency_key", name="uq_transactions_account_idempotency"
        ),
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint(
            "type IN ('DISBURSEMENT', 'PURCHASE', 'PAYMENT')", name="ck_transactions_type"
        ),
        CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'FAILED')", name="ck_transactions_status"
        ),
        Index(
            "ix_transactions_account_type_status",
            "account_id",
            "type",
            "status",
            postgresql_include=["amount"],
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("credit_accounts.id"))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, native_enum=False, create_constraint=False, length=16)
    )
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus, native_enum=False, create_constraint=False, length=16)
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 2, asdecimal=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
