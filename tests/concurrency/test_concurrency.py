"""Concurrency guarantees, exercised with real threads and independent PostgreSQL connections.

Spec: ledger-transactions / Concurrent purchases cannot oversubscribe credit,
Atomic state transitions, Idempotent transaction creation (concurrent requests);
account-balance / Account invariants (concurrent operations).
"""

import random
import threading
import time
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from ledger import repository
from ledger.domain.balance import Balance
from ledger.domain.errors import InsufficientCredit, InvalidStateTransition, Overpayment
from ledger.domain.records import Transaction
from ledger.service import CreateTransactionResult, LedgerService
from tests.support import D, S, T, assert_invariants, create, funded_account, run_concurrently


@pytest.fixture
def slow_balance_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Widen the race window between reading the balance and inserting the transaction."""
    original: Callable[[Session, UUID], Balance] = repository.get_balance

    def slow(session: Session, account_id: UUID) -> Balance:
        balance = original(session, account_id)
        time.sleep(0.3)
        return balance

    monkeypatch.setattr(repository, "get_balance", slow)


def account_with_available(service: LedgerService, available: str) -> UUID:
    """credit_granted = 1000.00 with (1000 - available) already outstanding."""
    account_id = funded_account(service, "1000.00")
    create(service, account_id, T.PURCHASE, str(D("1000.00") - D(available)), complete=True)
    return account_id


class TestConcurrentPurchases:
    def purchase(
        self, service: LedgerService, account_id: UUID, amount: str
    ) -> Callable[[int], CreateTransactionResult]:
        return lambda i: service.create_transaction(account_id, T.PURCHASE, amount, f"p-{i}")

    @pytest.mark.usefixtures("slow_balance_reads")
    def test_two_purchases_for_the_last_credit(self, service: LedgerService) -> None:
        account_id = account_with_available(service, "100.00")

        outcomes = run_concurrently(2, self.purchase(service, account_id, "80.00"))

        assert sum(o.ok for o in outcomes) == 1
        [failure] = [o.error for o in outcomes if not o.ok]
        assert isinstance(failure, InsufficientCredit)
        balance = assert_invariants(service, account_id)
        assert balance.reserved_credit == D("80.00")
        assert balance.available_credit == D("20.00")

    def test_many_purchases(self, service: LedgerService) -> None:
        account_id = funded_account(service, "1000.00")

        outcomes = run_concurrently(50, self.purchase(service, account_id, "30.00"))

        assert sum(o.ok for o in outcomes) == 33
        assert all(isinstance(o.error, InsufficientCredit) for o in outcomes if not o.ok)
        balance = assert_invariants(service, account_id)
        assert balance.reserved_credit == D("990.00")
        assert balance.available_credit == D("10.00")

    @pytest.mark.allow_invariant_violation
    @pytest.mark.usefixtures("slow_balance_reads")
    def test_negative_control_without_the_lock_credit_is_oversubscribed(
        self, service: LedgerService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proves the row lock is what prevents oversubscription, not luck or timing."""
        monkeypatch.setattr(repository, "lock_account", repository.get_account)
        account_id = account_with_available(service, "100.00")

        outcomes = run_concurrently(2, self.purchase(service, account_id, "80.00"))

        assert all(o.ok for o in outcomes)
        balance = service.get_balance(account_id)
        assert balance.available_credit == D("-60.00")
        assert balance.invariant_violations()


class TestConcurrentPayments:
    @pytest.mark.usefixtures("slow_balance_reads")
    def test_two_payments_cannot_overpay(self, service: LedgerService) -> None:
        account_id = account_with_available(service, "900.00")  # outstanding = 100.00

        outcomes = run_concurrently(
            2, lambda i: service.create_transaction(account_id, T.PAYMENT, "80.00", f"pay-{i}")
        )

        assert sum(o.ok for o in outcomes) == 1
        assert all(isinstance(o.error, Overpayment) for o in outcomes if not o.ok)
        for o in outcomes:
            if o.ok and o.value:
                service.complete_transaction(o.value.transaction.id)
        balance = assert_invariants(service, account_id)
        assert balance.outstanding_balance == D("20.00")


class TestConcurrentTransitions:
    def test_only_one_worker_completes_a_transaction(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        tx = create(service, account_id, T.PURCHASE, "100.00")

        outcomes = run_concurrently(10, lambda _: service.complete_transaction(tx.id))

        assert sum(o.ok for o in outcomes) == 1
        assert all(isinstance(o.error, InvalidStateTransition) for o in outcomes if not o.ok)
        balance = assert_invariants(service, account_id)
        assert balance.outstanding_balance == D("100.00")
        assert balance.reserved_credit == D("0.00")

    @pytest.mark.parametrize("round_", range(10))
    def test_complete_and_fail_race(self, service: LedgerService, round_: int) -> None:
        account_id = funded_account(service)
        tx = create(service, account_id, T.PURCHASE, "100.00")
        actions = [service.complete_transaction, service.fail_transaction]

        outcomes = run_concurrently(2, lambda i: actions[i](tx.id))

        [winner] = [o.value for o in outcomes if o.ok]
        [loser] = [o.error for o in outcomes if not o.ok]
        assert isinstance(loser, InvalidStateTransition)
        assert winner is not None
        [final] = [t for t in service.list_transactions(account_id) if t.id == tx.id]
        assert final.status is winner.status


class TestConcurrentIdempotency:
    def test_identical_requests_create_one_transaction(self, service: LedgerService) -> None:
        account_id = funded_account(service)

        outcomes = run_concurrently(
            10, lambda _: service.create_transaction(account_id, T.PURCHASE, "100.00", "same")
        )

        assert all(o.ok for o in outcomes)
        results = [o.value for o in outcomes if o.value]
        assert len({r.transaction.id for r in results}) == 1
        assert sum(r.created for r in results) == 1
        assert service.get_balance(account_id).reserved_credit == D("100.00")


def test_mixed_workload_preserves_invariants(service: LedgerService) -> None:
    """Purchases, payments and settlements racing, with readers checking every snapshot."""
    account_id = funded_account(service, "1000.00")
    create(service, account_id, T.PURCHASE, "400.00", complete=True)
    pending: list[Transaction] = []
    pending_lock = threading.Lock()
    stop_readers = threading.Event()
    snapshot_violations: list[list[str]] = []
    expected_errors = (InsufficientCredit, Overpayment, InvalidStateTransition)

    def writer(i: int) -> None:
        rng = random.Random(i)
        for n in range(15):
            action = rng.choice(["purchase", "payment", "settle", "settle"])
            try:
                if action == "settle":
                    with pending_lock:
                        if not pending:
                            continue
                        tx = pending.pop(rng.randrange(len(pending)))
                    if rng.random() < 0.7:
                        service.complete_transaction(tx.id)
                    else:
                        service.fail_transaction(tx.id)
                else:
                    amount = Decimal(rng.randint(1, 15000)) / 100
                    type_ = T.PURCHASE if action == "purchase" else T.PAYMENT
                    result = service.create_transaction(account_id, type_, amount, f"w{i}-{n}")
                    with pending_lock:
                        pending.append(result.transaction)
            except expected_errors:
                pass

    def reader() -> None:
        while not stop_readers.is_set():
            violations = service.get_balance(account_id).invariant_violations()
            if violations:
                snapshot_violations.append(violations)

    readers = [threading.Thread(target=reader) for _ in range(2)]
    for r in readers:
        r.start()
    try:
        outcomes = run_concurrently(12, writer)
    finally:
        stop_readers.set()
        for r in readers:
            r.join()

    assert [o.error for o in outcomes if not o.ok] == []
    assert snapshot_violations == []
    assert_invariants(service, account_id)
    statuses = {t.status for t in service.list_transactions(account_id)}
    assert S.COMPLETED in statuses
