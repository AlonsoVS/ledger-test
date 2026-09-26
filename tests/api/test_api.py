"""HTTP mapping: status codes, error codes and string-only amounts."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from ledger.api.app import create_app
from ledger.service import LedgerService


@pytest.fixture
def client(service: LedgerService) -> TestClient:
    return TestClient(create_app(service))


def new_account(client: TestClient) -> str:
    response = client.post("/accounts", json={"customer_id": "cust-1"})
    assert response.status_code == 201
    account_id: str = response.json()["id"]
    return account_id


def post_tx(client: TestClient, account_id: str, type_: str, amount: object, key: str) -> Response:
    response: Response = client.post(
        f"/accounts/{account_id}/transactions",
        json={"type": type_, "amount": amount},
        headers={"Idempotency-Key": key},
    )
    return response


def test_full_flow(client: TestClient) -> None:
    account_id = new_account(client)

    disbursement = post_tx(client, account_id, "DISBURSEMENT", "1000.00", "d1")
    assert disbursement.status_code == 201
    body = disbursement.json()
    assert body["status"] == "PENDING"
    assert body["amount"] == "1000.00"
    assert client.post(f"/transactions/{body['id']}/complete").status_code == 200

    purchase = post_tx(client, account_id, "PURCHASE", "300.00", "p1").json()
    client.post(f"/transactions/{purchase['id']}/complete")
    payment = post_tx(client, account_id, "PAYMENT", "120.50", "pay1").json()
    client.post(f"/transactions/{payment['id']}/complete")

    account = client.get(f"/accounts/{account_id}").json()
    assert account["balance"] == {
        "credit_granted": "1000.00",
        "outstanding_balance": "179.50",
        "reserved_credit": "0.00",
        "pending_payments": "0.00",
        "available_credit": "820.50",
    }
    assert len(client.get(f"/accounts/{account_id}/transactions").json()) == 3


def test_idempotent_replay_returns_200_and_conflict_409(client: TestClient) -> None:
    account_id = new_account(client)
    first = post_tx(client, account_id, "DISBURSEMENT", "100.00", "k")
    replay = post_tx(client, account_id, "DISBURSEMENT", "100.00", "k")
    conflict = post_tx(client, account_id, "DISBURSEMENT", "200.00", "k")

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_business_rule_rejections(client: TestClient) -> None:
    account_id = new_account(client)
    purchase = post_tx(client, account_id, "PURCHASE", "0.01", "p")
    payment = post_tx(client, account_id, "PAYMENT", "0.01", "pay")
    assert (purchase.status_code, purchase.json()["code"]) == (422, "INSUFFICIENT_CREDIT")
    assert (payment.status_code, payment.json()["code"]) == (422, "OVERPAYMENT")


@pytest.mark.parametrize("amount", ["-1.00", "0", "10.005"])
def test_invalid_amount(client: TestClient, amount: str) -> None:
    result = post_tx(client, new_account(client), "DISBURSEMENT", amount, "k")
    assert (result.status_code, result.json()["code"]) == (422, "INVALID_AMOUNT")


@pytest.mark.parametrize("amount", [10.1, 100])
def test_json_number_amount_is_rejected(client: TestClient, amount: float) -> None:
    result = post_tx(client, new_account(client), "DISBURSEMENT", amount, "k")
    assert result.status_code == 422


def test_missing_idempotency_key(client: TestClient) -> None:
    account_id = new_account(client)
    response = client.post(
        f"/accounts/{account_id}/transactions", json={"type": "DISBURSEMENT", "amount": "1.00"}
    )
    assert response.status_code == 422


def test_unknown_type_is_rejected(client: TestClient) -> None:
    assert post_tx(client, new_account(client), "REFUND", "1.00", "k").status_code == 422


def test_invalid_state_transition_is_409(client: TestClient) -> None:
    account_id = new_account(client)
    body = post_tx(client, account_id, "DISBURSEMENT", "100.00", "k").json()
    assert client.post(f"/transactions/{body['id']}/fail").status_code == 200
    response = client.post(f"/transactions/{body['id']}/complete")
    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_STATE_TRANSITION"


def test_not_found(client: TestClient) -> None:
    assert client.get(f"/accounts/{uuid4()}").status_code == 404
    assert client.post(f"/transactions/{uuid4()}/complete").status_code == 404
    assert post_tx(client, str(uuid4()), "DISBURSEMENT", "1.00", "k").status_code == 404
