# Credit Ledger

A small ledger for a revolving credit account: disbursements, purchases, partial
payments, and exact derivation of outstanding balance and available credit —
idempotent and safe under concurrency.

- Specification: [`docs/credit-ledger-spec.md`](docs/credit-ledger-spec.md)
- OpenSpec change (requirements + scenarios): [`openspec/changes/add-credit-ledger/`](openspec/changes/add-credit-ledger/)
- Design decisions and trade-offs: [`design.md`](openspec/changes/add-credit-ledger/design.md)

## Quick start

Requirements: [uv](https://docs.astral.sh/uv/), Docker.

```bash
make up        # PostgreSQL 16 on localhost:55432 (creates `ledger` and `ledger_test`)
uv sync        # Python 3.12 + dependencies
make migrate   # apply Alembic migrations to the dev database
make run       # API on http://localhost:8000  (OpenAPI docs at /docs)
make check     # ruff + mypy --strict + pytest
```

Configuration is via environment variables (see `.env.example`):
`LEDGER_DATABASE_URL`, and `LEDGER_TEST_DATABASE_URL` for the test suite.

## API

Amounts are **JSON strings** (`"120.50"`) in both directions; JSON numbers are rejected.

| Method | Path | Result |
|---|---|---|
| `POST` | `/accounts` `{"customer_id"}` | `201` account |
| `GET` | `/accounts/{id}` | account + derived balance |
| `POST` | `/accounts/{id}/transactions` `{"type", "amount"}` + `Idempotency-Key` header | `201` created, `200` idempotent replay |
| `GET` | `/accounts/{id}/transactions` | full ledger, including failed transactions |
| `POST` | `/transactions/{id}/complete` | `200`, or `409` if not `PENDING` |
| `POST` | `/transactions/{id}/fail` | `200`, or `409` if not `PENDING` |

Errors return `{"code", "message"}`: `404` (`ACCOUNT_NOT_FOUND`, `TRANSACTION_NOT_FOUND`),
`409` (`IDEMPOTENCY_CONFLICT`, `INVALID_STATE_TRANSITION`),
`422` (`INSUFFICIENT_CREDIT`, `OVERPAYMENT`, `INVALID_AMOUNT`, `INVALID_REQUEST`).

```bash
A=$(curl -s -X POST localhost:8000/accounts -H 'content-type: application/json' \
      -d '{"customer_id":"cust-1"}' | jq -r .id)
T=$(curl -s -X POST localhost:8000/accounts/$A/transactions -H 'content-type: application/json' \
      -H 'Idempotency-Key: disb-1' -d '{"type":"DISBURSEMENT","amount":"1000.00"}' | jq -r .id)
curl -s -X POST localhost:8000/transactions/$T/complete
curl -s localhost:8000/accounts/$A | jq .balance
```

## Domain model

```text
credit_granted      = Σ DISBURSEMENT[COMPLETED]
outstanding_balance = Σ PURCHASE[COMPLETED] − Σ PAYMENT[COMPLETED]
reserved_credit     = Σ PURCHASE[PENDING]
pending_payments    = Σ PAYMENT[PENDING]
available_credit    = credit_granted − outstanding_balance − reserved_credit
```

Invariants held after every committed operation:
`available_credit ≥ 0`, `outstanding_balance ≥ 0`, `outstanding_balance − pending_payments ≥ 0`,
credit conservation, positive amounts, immutable terminal states, unique
`(account_id, idempotency_key)`.

Transactions are created `PENDING` and move once to `COMPLETED` or `FAILED`.
A pending purchase reserves credit; a failed one releases it. Payments reduce debt
only when completed, and cannot exceed `outstanding − pending_payments`.

## How correctness is enforced

| Concern | Mechanism | Where |
|---|---|---|
| Exact money | `Decimal` end to end, `NUMERIC(19,2)`, >2 decimals rejected (never rounded), string-only JSON | `domain/money.py`, `api/schemas.py` |
| No stored balance | Balance derived from the ledger in **one** aggregate query (single snapshot) | `repository.get_balance` |
| Oversubscription (purchases) and overpayment (payments) | `SELECT … FOR UPDATE` on the account row before reading the balance and inserting | `service._create_transaction` |
| Duplicate / conflicting requests | Idempotency lookup under the lock, **before** business rules; unique constraint as backstop | `service._create_transaction` |
| Double application of a transition | `UPDATE … WHERE status = 'PENDING' RETURNING`; zero rows ⇒ rejected | `repository.transition_if_pending` |

Transitions take no account lock: no transition can break an invariant
(purchase completion keeps `available` constant; failures and disbursements only
add availability; payment completion was pre-validated at creation).

## Tests

```text
tests/unit/          money validation, state machine, balance math, business rules
tests/integration/   lifecycle, payments, failures, idempotency (real PostgreSQL)
tests/concurrency/   threads + barrier + independent connections (real PostgreSQL)
tests/api/           HTTP status/error mapping, string amounts
```

- After **every** database test, a fixture checks the invariants of every account and
  cross-checks the SQL balance against an independent Python fold over the ledger.
- Concurrency tests widen the race window (a slowed balance read) so the lock is
  genuinely exercised. A **negative control** removes the lock and shows two
  concurrent purchases then oversubscribe credit — proving the lock is what prevents it.

## Trade-offs and non-goals

- Creation is serialised per account; fine here, limiting for very hot accounts.
- Balance aggregation grows with ledger size (covering index mitigates); a
  materialised projection would be the next step.
- Pending purchases never expire; overpayment/credit balances are not modelled.
- Out of scope: interest, fees, multi-currency, auth, customers, external
  providers, double-entry accounting.
