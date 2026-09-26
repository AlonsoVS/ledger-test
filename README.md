# Credit Ledger

A small ledger for a revolving credit account: disbursements, purchases, partial
payments, and exact derivation of outstanding balance and available credit —
idempotent and safe under concurrency.

- Specification: [`docs/credit-ledger-spec.md`](docs/credit-ledger-spec.md)
- Current requirements + scenarios: [`openspec/specs/`](openspec/specs/) (`credit-accounts`, `account-balance`, `ledger-transactions`)
- Design decisions and trade-offs: [`design.md`](openspec/changes/archive/2026-09-25-add-credit-ledger/design.md) (archived change `add-credit-ledger`)

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
payment_capacity    = outstanding_balance − pending_payments
```

Invariants held after every committed operation:
`available_credit ≥ 0`, `outstanding_balance ≥ 0`, `payment_capacity ≥ 0`,
credit conservation, positive amounts, immutable terminal states, unique
`(account_id, idempotency_key)`.

Transactions are created `PENDING` and move once to `COMPLETED` or `FAILED`.
A pending purchase reserves credit; completing it turns the reservation into debt,
failing it releases it. Payments work the same way on the other side. A pending
payment leaves outstanding and available unchanged but reserves **payment
capacity** (`amount ≤ payment_capacity` at creation). Completing it reduces debt and
uses up the reservation. Failing it releases the reservation.

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
add availability; payment completion uses up capacity that the pending payment
already reserved, since outstanding and pending payments fall by the same amount,
so `payment_capacity` is unchanged).

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

## Decisions and Trade-offs

### Ledger as source of truth

The transaction ledger is the single source of truth. Account balances are
derived from ledger transactions rather than stored as mutable state.

This avoids multiple sources of truth and makes the financial history
auditable. The trade-off is that balance calculation becomes more expensive
as the ledger grows; a materialized projection could be introduced later.

### Simplified ledger instead of double-entry accounting

The implementation uses a simplified ledger rather than a full double-entry
accounting model because the exercise only requires modeling a single credit
account.

A full double-entry model would provide stronger accounting semantics but
would introduce additional accounts and entries that are unnecessary for
the scope of this exercise.

### Account-level pessimistic locking

Transaction creation uses `SELECT ... FOR UPDATE` on the credit account.

This serializes operations whose validation depends on the current ledger
state, including purchases and payments. The trade-off is reduced
concurrency for highly contended accounts.

### Idempotency

The pair `(account_id, idempotency_key)` is unique.

Identical retries return the existing transaction, while reuse of the same
key with different parameters is rejected.

The application performs the idempotency check before business validation,
while the database constraint provides the final concurrency-safe guarantee.

### Conditional state transitions

Transaction completion/failure uses an atomic conditional update:

```sql
UPDATE transactions
SET status = ...
WHERE id = ...
  AND status = 'PENDING'
```

This prevents the same transaction from being transitioned twice without
requiring an account-level lock for every state transition.

### Out of scope

- Pending purchases never expire; overpayment/credit balances are not modelled.
- Interest, fees, multi-currency, auth, customers, external providers.
