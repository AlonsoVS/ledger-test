"""Shared helpers for database-backed tests."""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from ledger.domain.balance import Balance
from ledger.domain.enums import TransactionStatus, TransactionType
from ledger.domain.records import Transaction
from ledger.service import LedgerService

D = Decimal
T = TransactionType
S = TransactionStatus


def new_key() -> str:
    return str(uuid4())


def create(
    service: LedgerService,
    account_id: UUID,
    type_: TransactionType,
    amount: str,
    *,
    key: str | None = None,
    complete: bool = False,
) -> Transaction:
    tx = service.create_transaction(account_id, type_, amount, key or new_key()).transaction
    return service.complete_transaction(tx.id) if complete else tx


def funded_account(service: LedgerService, credit: str = "1000.00") -> UUID:
    account_id = service.create_account("cust-test").id
    create(service, account_id, T.DISBURSEMENT, credit, complete=True)
    return account_id


def recompute_balance(transactions: list[Transaction]) -> Balance:
    """Independent Python derivation of the balance, used to cross-check the SQL aggregate."""

    def total(type_: TransactionType, status: TransactionStatus) -> Decimal:
        return sum(
            (t.amount for t in transactions if t.type is type_ and t.status is status), D("0.00")
        )

    return Balance(
        credit_granted=total(T.DISBURSEMENT, S.COMPLETED),
        outstanding_balance=total(T.PURCHASE, S.COMPLETED) - total(T.PAYMENT, S.COMPLETED),
        reserved_credit=total(T.PURCHASE, S.PENDING),
        pending_payments=total(T.PAYMENT, S.PENDING),
    )


def assert_invariants(service: LedgerService, account_id: UUID) -> Balance:
    balance = service.get_balance(account_id)
    assert balance.invariant_violations() == [], balance
    assert balance == recompute_balance(service.list_transactions(account_id))
    return balance


@dataclass(frozen=True)
class Outcome[R]:
    value: R | None = None
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def run_concurrently[R](n: int, fn: Callable[[int], R]) -> list[Outcome[R]]:
    """Run `fn(i)` for i in range(n) on n threads released at the same instant."""
    barrier = threading.Barrier(n, timeout=30)

    def worker(i: int) -> Outcome[R]:
        barrier.wait()
        try:
            return Outcome(value=fn(i))
        except Exception as exc:
            return Outcome(error=exc)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(worker, range(n)))
