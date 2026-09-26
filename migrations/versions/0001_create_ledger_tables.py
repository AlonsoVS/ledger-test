"""Create credit_accounts and transactions tables.

Revision ID: 0001
Revises:
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credit_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("credit_accounts.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(19, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "account_id", "idempotency_key", name="uq_transactions_account_idempotency"
        ),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        sa.CheckConstraint(
            "type IN ('DISBURSEMENT', 'PURCHASE', 'PAYMENT')", name="ck_transactions_type"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'FAILED')", name="ck_transactions_status"
        ),
    )
    op.create_index(
        "ix_transactions_account_type_status",
        "transactions",
        ["account_id", "type", "status"],
        postgresql_include=["amount"],
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_account_type_status", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("credit_accounts")
