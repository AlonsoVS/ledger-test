"""Idempotent transaction creation (spec: ledger-transactions / Idempotent transaction creation)."""

import pytest

from ledger.domain.errors import IdempotencyConflict, InvalidRequest
from ledger.service import LedgerService
from tests.support import D, S, T, create, funded_account


def test_identical_replay_returns_same_transaction(service: LedgerService) -> None:
    account_id = funded_account(service)
    first = service.create_transaction(account_id, T.PURCHASE, "100.00", "abc")
    second = service.create_transaction(account_id, T.PURCHASE, "100.00", "abc")

    assert first.created is True
    assert second.created is False
    assert second.transaction == first.transaction
    assert [t.idempotency_key for t in service.list_transactions(account_id)].count("abc") == 1
    assert service.get_balance(account_id).reserved_credit == D("100.00")


def test_equivalent_amount_representation_is_a_replay(service: LedgerService) -> None:
    account_id = funded_account(service)
    first = service.create_transaction(account_id, T.PURCHASE, "100", "abc")
    second = service.create_transaction(account_id, T.PURCHASE, "100.00", "abc")
    assert second.created is False
    assert second.transaction.id == first.transaction.id


@pytest.mark.parametrize(("type_", "amount"), [(T.PURCHASE, "200.00"), (T.DISBURSEMENT, "100.00")])
def test_conflicting_replay_is_rejected(service: LedgerService, type_: T, amount: str) -> None:
    account_id = funded_account(service)
    original = service.create_transaction(account_id, T.PURCHASE, "100.00", "abc").transaction
    before = service.list_transactions(account_id)

    with pytest.raises(IdempotencyConflict):
        service.create_transaction(account_id, type_, amount, "abc")

    assert service.list_transactions(account_id) == before
    assert original in before


def test_replay_after_credit_exhausted_returns_original(service: LedgerService) -> None:
    account_id = funded_account(service, "100.00")
    first = service.create_transaction(account_id, T.PURCHASE, "100.00", "abc")
    assert service.get_balance(account_id).available_credit == D("0.00")

    replay = service.create_transaction(account_id, T.PURCHASE, "100.00", "abc")

    assert replay.created is False
    assert replay.transaction.id == first.transaction.id


def test_replay_of_failed_transaction_returns_it(service: LedgerService) -> None:
    account_id = funded_account(service)
    tx = create(service, account_id, T.PURCHASE, "100.00", key="abc")
    service.fail_transaction(tx.id)

    replay = service.create_transaction(account_id, T.PURCHASE, "100.00", "abc")

    assert replay.created is False
    assert replay.transaction.id == tx.id
    assert replay.transaction.status is S.FAILED
    assert len(service.list_transactions(account_id)) == 2  # disbursement + failed purchase


def test_rejected_request_does_not_consume_the_key(service: LedgerService) -> None:
    account_id = funded_account(service, "100.00")
    with pytest.raises(Exception, match="exceeds available credit"):
        service.create_transaction(account_id, T.PURCHASE, "150.00", "abc")

    create(service, account_id, T.DISBURSEMENT, "100.00", complete=True)
    retry = service.create_transaction(account_id, T.PURCHASE, "150.00", "abc")
    assert retry.created is True


def test_same_key_on_different_accounts_is_independent(service: LedgerService) -> None:
    a, b = funded_account(service), funded_account(service)
    tx_a = service.create_transaction(a, T.PURCHASE, "100.00", "abc").transaction
    tx_b = service.create_transaction(b, T.PURCHASE, "250.00", "abc").transaction
    assert tx_a.id != tx_b.id


@pytest.mark.parametrize("key", ["", "k" * 256])
def test_invalid_idempotency_key(service: LedgerService, key: str) -> None:
    account_id = funded_account(service)
    with pytest.raises(InvalidRequest):
        service.create_transaction(account_id, T.PURCHASE, "1.00", key)
