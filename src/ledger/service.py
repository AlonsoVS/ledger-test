"""Use cases. Each public method runs in exactly one database transaction."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ledger import repository as repo
from ledger.domain.balance import Balance
from ledger.domain.enums import TransactionStatus, TransactionType
from ledger.domain.errors import (
    AccountNotFound,
    IdempotencyConflict,
    InvalidRequest,
    InvalidStateTransition,
    TransactionNotFound,
)
from ledger.domain.money import parse_amount
from ledger.domain.records import Account, Transaction
from ledger.domain.rules import ensure_can_create
from ledger.domain.state import can_transition

MAX_CUSTOMER_ID_LENGTH = 64
MAX_IDEMPOTENCY_KEY_LENGTH = 255
IDEMPOTENCY_CONSTRAINT = "uq_transactions_account_idempotency"


@dataclass(frozen=True, slots=True)
class CreateTransactionResult:
    transaction: Transaction
    created: bool  # False when an identical earlier request was replayed


@dataclass(frozen=True, slots=True)
class AccountView:
    account: Account
    balance: Balance


class LedgerService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create_account(self, customer_id: str) -> Account:
        customer_id = customer_id.strip()
        if not customer_id or len(customer_id) > MAX_CUSTOMER_ID_LENGTH:
            raise InvalidRequest(
                f"customer_id must be 1-{MAX_CUSTOMER_ID_LENGTH} non-blank characters"
            )
        with self._sessions.begin() as session:
            return repo.insert_account(session, customer_id)

    def get_account(self, account_id: UUID) -> AccountView:
        with self._sessions.begin() as session:
            account = repo.get_account(session, account_id)
            if account is None:
                raise AccountNotFound(account_id)
            return AccountView(account, repo.get_balance(session, account_id))

    def get_balance(self, account_id: UUID) -> Balance:
        return self.get_account(account_id).balance

    def list_transactions(self, account_id: UUID) -> list[Transaction]:
        with self._sessions.begin() as session:
            if repo.get_account(session, account_id) is None:
                raise AccountNotFound(account_id)
            return repo.list_transactions(session, account_id)

    def create_transaction(
        self,
        account_id: UUID,
        type_: TransactionType,
        amount: Decimal | str | int,
        idempotency_key: str,
    ) -> CreateTransactionResult:
        if not idempotency_key or len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            raise InvalidRequest(
                f"idempotency_key must be 1-{MAX_IDEMPOTENCY_KEY_LENGTH} characters"
            )
        parsed_amount = parse_amount(amount)
        try:
            return self._create_transaction(account_id, type_, parsed_amount, idempotency_key)
        except IntegrityError as exc:
            # Backstop only: the account lock serialises same-key requests, so this path should
            # be unreachable. If it is ever hit, the concurrent winner has committed and the
            # retry resolves to a replay or a conflict.
            if IDEMPOTENCY_CONSTRAINT not in str(exc.orig):
                raise
            return self._create_transaction(account_id, type_, parsed_amount, idempotency_key)

    def _create_transaction(
        self, account_id: UUID, type_: TransactionType, amount: Decimal, idempotency_key: str
    ) -> CreateTransactionResult:
        with self._sessions.begin() as session:
            # 1. Serialise all creations on this account. Held until commit/rollback.
            if repo.lock_account(session, account_id) is None:
                raise AccountNotFound(account_id)

            # 2. Idempotency before business rules: a replay of a request that succeeded must
            #    return the original transaction even if the rules would now reject it.
            existing = repo.find_by_idempotency_key(session, account_id, idempotency_key)
            if existing is not None:
                if not existing.matches(type_, amount):
                    raise IdempotencyConflict(idempotency_key)
                return CreateTransactionResult(existing, created=False)

            # 3. Business rules against a balance nobody else can change while we hold the lock.
            ensure_can_create(repo.get_balance(session, account_id), type_, amount)

            transaction = repo.insert_transaction(
                session, account_id, idempotency_key, type_, amount
            )
            return CreateTransactionResult(transaction, created=True)

    def complete_transaction(self, transaction_id: UUID) -> Transaction:
        return self._transition(transaction_id, TransactionStatus.COMPLETED)

    def fail_transaction(self, transaction_id: UUID) -> Transaction:
        return self._transition(transaction_id, TransactionStatus.FAILED)

    def _transition(self, transaction_id: UUID, target: TransactionStatus) -> Transaction:
        # No account lock: no transition can break an invariant (see design D3), and the
        # conditional update guarantees each transaction's effect is applied at most once.
        if not can_transition(TransactionStatus.PENDING, target):
            raise ValueError(f"{target} is not a valid transition target")
        with self._sessions.begin() as session:
            updated = repo.transition_if_pending(session, transaction_id, target)
            if updated is not None:
                return updated
            current = repo.get_transaction(session, transaction_id)
            if current is None:
                raise TransactionNotFound(transaction_id)
            raise InvalidStateTransition(transaction_id, current.status, target)
