"""Transaction lifecycle and balance derivation (spec: account-balance, ledger-transactions)."""

from uuid import uuid4

import pytest

from ledger.domain.errors import (
    AccountNotFound,
    InsufficientCredit,
    InvalidAmount,
    InvalidRequest,
    InvalidStateTransition,
    Overpayment,
    TransactionNotFound,
)
from ledger.service import LedgerService
from tests.support import D, S, T, assert_invariants, create, funded_account


class TestAccounts:
    def test_new_account_has_zero_balance(self, service: LedgerService) -> None:
        account = service.create_account("cust-1")
        balance = assert_invariants(service, account.id)
        assert account.customer_id == "cust-1"
        assert balance.credit_granted == D("0.00")
        assert balance.outstanding_balance == D("0.00")
        assert balance.reserved_credit == D("0.00")
        assert balance.available_credit == D("0.00")

    def test_blank_customer_id_is_rejected(self, service: LedgerService) -> None:
        with pytest.raises(InvalidRequest):
            service.create_account("   ")

    def test_unknown_account(self, service: LedgerService) -> None:
        with pytest.raises(AccountNotFound):
            service.create_transaction(uuid4(), T.DISBURSEMENT, "10.00", "k")
        with pytest.raises(AccountNotFound):
            service.get_balance(uuid4())


def test_basic_lifecycle(service: LedgerService) -> None:
    account_id = service.create_account("cust-1").id
    create(service, account_id, T.DISBURSEMENT, "1000.00", complete=True)
    create(service, account_id, T.PURCHASE, "300.00", complete=True)
    create(service, account_id, T.PAYMENT, "120.50", complete=True)

    balance = assert_invariants(service, account_id)
    assert balance.credit_granted == D("1000.00")
    assert balance.outstanding_balance == D("179.50")
    assert balance.reserved_credit == D("0.00")
    assert balance.pending_payments == D("0.00")
    assert balance.available_credit == D("820.50")


def test_subsequent_disbursements_accumulate(service: LedgerService) -> None:
    account_id = funded_account(service, "1000.00")
    create(service, account_id, T.DISBURSEMENT, "250.25", complete=True)
    assert service.get_balance(account_id).credit_granted == D("1250.25")


class TestDisbursement:
    def test_pending_disbursement_has_no_effect(self, service: LedgerService) -> None:
        account_id = service.create_account("cust-1").id
        tx = create(service, account_id, T.DISBURSEMENT, "1000.00")
        assert tx.status is S.PENDING
        assert service.get_balance(account_id).available_credit == D("0.00")

    def test_failed_disbursement_grants_nothing(self, service: LedgerService) -> None:
        account_id = service.create_account("cust-1").id
        tx = create(service, account_id, T.DISBURSEMENT, "500.00")
        service.fail_transaction(tx.id)
        balance = service.get_balance(account_id)
        assert balance.credit_granted == D("0.00")
        assert balance.available_credit == D("0.00")


class TestPurchase:
    def test_pending_purchase_reserves_credit(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        tx = create(service, account_id, T.PURCHASE, "400.00")
        balance = service.get_balance(account_id)
        assert tx.status is S.PENDING
        assert balance.reserved_credit == D("400.00")
        assert balance.outstanding_balance == D("0.00")
        assert balance.available_credit == D("600.00")

    def test_completion_moves_reserved_to_outstanding(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        tx = create(service, account_id, T.PURCHASE, "200.00")
        before = service.get_balance(account_id)

        service.complete_transaction(tx.id)
        after = service.get_balance(account_id)

        assert after.reserved_credit == before.reserved_credit - D("200.00")
        assert after.outstanding_balance == before.outstanding_balance + D("200.00")
        assert after.available_credit == before.available_credit == D("800.00")

    def test_failure_releases_reservation(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        tx = create(service, account_id, T.PURCHASE, "200.00")
        assert service.get_balance(account_id).available_credit == D("800.00")

        failed = service.fail_transaction(tx.id)
        balance = service.get_balance(account_id)

        assert balance.reserved_credit == D("0.00")
        assert balance.available_credit == D("1000.00")
        # The failed purchase stays in the ledger with its original amount.
        [listed] = [t for t in service.list_transactions(account_id) if t.id == tx.id]
        assert listed.status is S.FAILED == failed.status
        assert listed.amount == D("200.00")

    def test_purchase_exactly_equal_to_available_credit(self, service: LedgerService) -> None:
        account_id = funded_account(service, "100.00")
        create(service, account_id, T.PURCHASE, "100.00")
        assert service.get_balance(account_id).available_credit == D("0.00")

    def test_insufficient_credit_persists_nothing(self, service: LedgerService) -> None:
        account_id = funded_account(service, "100.00")
        before = service.list_transactions(account_id)

        with pytest.raises(InsufficientCredit):
            create(service, account_id, T.PURCHASE, "100.01")

        assert service.list_transactions(account_id) == before
        assert service.get_balance(account_id).available_credit == D("100.00")

    def test_pending_reservations_count_against_availability(self, service: LedgerService) -> None:
        account_id = funded_account(service, "100.00")
        create(service, account_id, T.PURCHASE, "80.00")
        with pytest.raises(InsufficientCredit):
            create(service, account_id, T.PURCHASE, "80.00")

    def test_exact_arithmetic(self, service: LedgerService) -> None:
        account_id = funded_account(service, "1.00")
        for amount in ("0.10", "0.20", "0.70"):
            create(service, account_id, T.PURCHASE, amount, complete=True)
        balance = service.get_balance(account_id)
        assert balance.outstanding_balance == D("1.00")
        assert balance.available_credit == D("0.00")


class TestPayment:
    def test_pending_payment_does_not_change_balance(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        create(service, account_id, T.PURCHASE, "300.00", complete=True)

        tx = create(service, account_id, T.PAYMENT, "100.00")
        balance = service.get_balance(account_id)

        assert tx.status is S.PENDING
        assert balance.outstanding_balance == D("300.00")
        assert balance.available_credit == D("700.00")
        # No effect on outstanding or available, but the payment reserves payment capacity.
        assert balance.pending_payments == D("100.00")
        assert balance.payment_capacity == D("200.00")

    def test_completed_payment_releases_credit(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        create(service, account_id, T.PURCHASE, "300.00", complete=True)
        tx = create(service, account_id, T.PAYMENT, "100.00")

        before = service.get_balance(account_id)
        service.complete_transaction(tx.id)
        balance = service.get_balance(account_id)

        assert balance.outstanding_balance == D("200.00")
        assert balance.available_credit == D("800.00")
        assert balance.pending_payments == D("0.00")
        # Completion consumes the reservation: capacity is unchanged, not re-checked.
        assert balance.payment_capacity == before.payment_capacity == D("200.00")

    def test_failed_payment_has_no_effect(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        create(service, account_id, T.PURCHASE, "300.00", complete=True)
        tx = create(service, account_id, T.PAYMENT, "100.00")

        service.fail_transaction(tx.id)
        balance = service.get_balance(account_id)

        assert balance.outstanding_balance == D("300.00")
        assert balance.available_credit == D("700.00")
        assert balance.pending_payments == D("0.00")
        assert balance.payment_capacity == D("300.00")

    def test_full_payment(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        create(service, account_id, T.PURCHASE, "300.00", complete=True)
        create(service, account_id, T.PAYMENT, "300.00", complete=True)
        assert service.get_balance(account_id).available_credit == D("1000.00")

    def test_overpayment_is_rejected(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        create(service, account_id, T.PURCHASE, "300.00", complete=True)
        with pytest.raises(Overpayment):
            create(service, account_id, T.PAYMENT, "300.01")

    def test_pending_payments_count_against_limit(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        create(service, account_id, T.PURCHASE, "300.00", complete=True)
        create(service, account_id, T.PAYMENT, "250.00")
        with pytest.raises(Overpayment):
            create(service, account_id, T.PAYMENT, "60.00")

    def test_failed_payment_releases_its_reservation(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        create(service, account_id, T.PURCHASE, "300.00", complete=True)
        pending = create(service, account_id, T.PAYMENT, "250.00")
        with pytest.raises(Overpayment):
            create(service, account_id, T.PAYMENT, "300.00")

        service.fail_transaction(pending.id)

        assert service.get_balance(account_id).payment_capacity == D("300.00")
        create(service, account_id, T.PAYMENT, "300.00")

    def test_payment_without_debt_is_rejected(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        with pytest.raises(Overpayment):
            create(service, account_id, T.PAYMENT, "0.01")

    def test_pending_purchase_adds_no_payment_capacity(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        create(service, account_id, T.PURCHASE, "300.00")  # reserved, not outstanding
        with pytest.raises(Overpayment):
            create(service, account_id, T.PAYMENT, "100.00")


class TestStateMachine:
    @pytest.mark.parametrize("first", ["complete", "fail"])
    @pytest.mark.parametrize("second", ["complete", "fail"])
    def test_terminal_states_cannot_transition(
        self, service: LedgerService, first: str, second: str
    ) -> None:
        account_id = funded_account(service)
        tx = create(service, account_id, T.PURCHASE, "10.00")
        settled = getattr(service, f"{first}_transaction")(tx.id)

        with pytest.raises(InvalidStateTransition) as excinfo:
            getattr(service, f"{second}_transaction")(tx.id)

        assert excinfo.value.current is settled.status
        [listed] = [t for t in service.list_transactions(account_id) if t.id == tx.id]
        assert listed.status is settled.status
        assert listed.updated_at == settled.updated_at

    def test_transition_advances_updated_at(self, service: LedgerService) -> None:
        account_id = funded_account(service)
        tx = create(service, account_id, T.PURCHASE, "10.00")
        assert service.complete_transaction(tx.id).updated_at > tx.updated_at

    def test_unknown_transaction(self, service: LedgerService) -> None:
        with pytest.raises(TransactionNotFound):
            service.complete_transaction(uuid4())


class TestAmountValidation:
    @pytest.mark.parametrize("amount", ["-100.00", "0.00", "10.005", "abc"])
    def test_invalid_amounts_persist_nothing(self, service: LedgerService, amount: str) -> None:
        account_id = funded_account(service)
        before = service.list_transactions(account_id)
        with pytest.raises(InvalidAmount):
            create(service, account_id, T.PAYMENT, amount)
        assert service.list_transactions(account_id) == before


def test_failed_transactions_are_audited_but_ignored(service: LedgerService) -> None:
    account_id = funded_account(service)
    create(service, account_id, T.PURCHASE, "300.00", complete=True)
    for type_, amount in [(T.DISBURSEMENT, "500.00"), (T.PURCHASE, "50.00"), (T.PAYMENT, "20.00")]:
        service.fail_transaction(create(service, account_id, type_, amount).id)

    balance = assert_invariants(service, account_id)
    assert balance.credit_granted == D("1000.00")
    assert balance.outstanding_balance == D("300.00")
    assert balance.available_credit == D("700.00")

    listed = service.list_transactions(account_id)
    assert [t.status for t in listed] == [S.COMPLETED, S.COMPLETED, S.FAILED, S.FAILED, S.FAILED]
    assert [t.created_at for t in listed] == sorted(t.created_at for t in listed)
