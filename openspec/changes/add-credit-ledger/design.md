# Design: Credit account ledger

The source specification lives in `docs/credit-ledger-spec.md`. This document
records the technical decisions, including the refinements made during design
review (marked **[R#]**).

## Context
- Revolving credit facility, single currency, no interest or fees.
- The ledger is the only source of financial truth; balances are derived.
- Must be correct under concurrent purchases and concurrent state transitions,
  and safe under client retries.

## Goals / Non-Goals
- Goals: exact arithmetic; invariants that cannot be violated by concurrency or
  retries; a small, readable codebase whose tests demonstrate the reasoning.
- Non-Goals: throughput optimisation for hot accounts, projections/caching,
  double-entry accounting, anything listed as out of scope in the proposal.

## Data Model

```sql
CREATE TABLE credit_accounts (
  id          UUID PRIMARY KEY,
  customer_id VARCHAR(64)  NOT NULL,
  created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE transactions (
  id              UUID PRIMARY KEY,
  account_id      UUID          NOT NULL REFERENCES credit_accounts(id),
  idempotency_key VARCHAR(255)  NOT NULL,
  type            VARCHAR(16)   NOT NULL
                  CHECK (type IN ('DISBURSEMENT','PURCHASE','PAYMENT')),
  status          VARCHAR(16)   NOT NULL
                  CHECK (status IN ('PENDING','COMPLETED','FAILED')),
  amount          NUMERIC(19,2) NOT NULL CHECK (amount > 0),
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT uq_transactions_account_idempotency
    UNIQUE (account_id, idempotency_key)
);

CREATE INDEX ix_transactions_account_type_status
  ON transactions (account_id, type, status) INCLUDE (amount);
```

`CHECK` constraints are defence in depth; the application validates first.
`VARCHAR + CHECK` is used instead of native PG enums to keep migrations simple.

## Balance derivation

```text
credit_granted      = Σ DISBURSEMENT[COMPLETED]
outstanding_balance = Σ PURCHASE[COMPLETED] − Σ PAYMENT[COMPLETED]
reserved_credit     = Σ PURCHASE[PENDING]
pending_payments    = Σ PAYMENT[PENDING]
available_credit    = credit_granted − outstanding_balance − reserved_credit
```

`pending_payments` is informational in the balance view and is required by the
overpayment rule [R1]. Conservation (`credit_granted = available + outstanding +
reserved`) holds by construction of `available_credit`; the meaningful guarantees
are therefore the non-negativity invariants below, which tests must assert.

## Decisions

### D1. Pessimistic account lock for all transaction creation
Every create use case runs:

```text
BEGIN
SELECT ... FROM credit_accounts WHERE id = :id FOR UPDATE   -- 404 if missing
look up (account_id, idempotency_key)                       -- see D4
compute balance (single query, D2)
validate type-specific rule (purchase: amount ≤ available;
                             payment:  amount ≤ outstanding − pending_payments)
INSERT transaction (status = PENDING)
COMMIT
```

The original spec locks only for purchases. We lock for **all three types**
because (a) payments now need a check too [R1], (b) it serialises same-key
replays so the idempotency path is deterministic [R3], and (c) the cost is one
indexed row lock. Only one lock is ever held per DB transaction, so deadlocks
between these operations are impossible.

Alternatives: optimistic version column (adds mutable coordination state and
retry loops); `SERIALIZABLE` isolation (correct, but the boundary is implicit
and callers must handle serialization failures). Rejected for clarity.

### D2. Balance computed in one aggregate statement  [R2]
All five quantities are computed with a single `SELECT` using
`SUM(amount) FILTER (WHERE type = ... AND status = ...)` and `COALESCE(..., 0)`.
Under `READ COMMITTED`, each statement sees one consistent snapshot. Computing
the sums in separate statements could observe a concurrent `PENDING → COMPLETED`
purchase transition between them and double-count or miss that amount.

### D3. State transitions via conditional update, no account lock
```sql
UPDATE transactions SET status = :target, updated_at = now()
WHERE id = :id AND status = 'PENDING'
RETURNING *;
```
One row → success. Zero rows → load the row: missing ⇒ `TransactionNotFound`,
otherwise ⇒ `InvalidStateTransition` (includes the current status).

No account lock is needed because no transition can violate an invariant:
- PURCHASE → COMPLETED moves `reserved → outstanding`; available unchanged.
- PURCHASE → FAILED and DISBURSEMENT → COMPLETED only increase available.
- PAYMENT → COMPLETED decreases outstanding by an amount already guaranteed to
  fit by [R1] (see D5).
- Everything → FAILED except purchases has no financial effect.

Re-completing an already-completed transaction is reported as
`InvalidStateTransition` (not a silent no-op) so the concurrent-transition test
can assert exactly one winner.

### D4. Idempotency check precedes business validation  [R3]
Inside the account lock, the service first looks up the key:
- found, same `(type, amount)` → return the existing transaction unchanged
  (whatever its current status, including `FAILED`); HTTP `200`.
- found, different parameters → `IdempotencyConflict`; HTTP `409`.
- not found → validate and insert; HTTP `201`.

Checking before the availability rule matters: a retry of a purchase that
succeeded earlier must return the original transaction even if credit is now
exhausted, instead of failing with "insufficient credit".

Amounts are compared as `Decimal` values after validation, so `100` and
`100.00` are the same request. `account_id` is implicit in the lookup.

Rejected requests (insufficient credit, overpayment, validation errors) persist
nothing, so a retry with the same key is re-evaluated against current state.

The unique constraint remains as a backstop: an `IntegrityError` on insert is
caught, the DB transaction rolled back, and the lookup re-run. With D1 this path
should be unreachable, but it keeps correctness independent of the lock.

### D5. Overpayment protection  [R1]
A payment is created only if
`amount ≤ outstanding_balance − pending_payments`.
This maintains the invariant `outstanding_balance − pending_payments ≥ 0`:
- payment creation is checked under the lock;
- payment completion moves the amount from `pending_payments` to a reduction of
  `outstanding`, leaving the difference unchanged;
- payment failure only increases the difference;
- purchase completion only increases `outstanding`.

Hence `outstanding_balance ≥ 0` always, and `available_credit ≤ credit_granted`.
Credit balances (customer overpaying) are out of scope.

### D6. Money handling  [R4]
- Domain type: `Decimal`. Validation rejects (never rounds): non-finite values,
  `≤ 0`, more than 2 decimal places, more than 17 integer digits (NUMERIC(19,2)).
- Values are normalised with `quantize(Decimal("0.01"))` after validation.
- HTTP: amounts are **JSON strings** (`"100.50"`) in requests and responses. A
  JSON number is rejected with `422`, to rule out any float parsing path.
- The DB column type maps to `Decimal` via SQLAlchemy `Numeric(19, 2,
  asdecimal=True)`.

### D7. Layering
```
src/ledger/
  domain/      money.py, enums.py, errors.py, balance.py (pure), state.py
  db/          models.py, session.py
  repository.py   SQL: lock account, find by key, insert, conditional update,
                  aggregate balance
  service.py      use cases; owns the DB transaction boundary
  api/            app.py, schemas.py, errors.py (exception → HTTP mapping)
migrations/       Alembic
tests/            unit/, integration/, concurrency/, api/
```

### D8. HTTP API (thin)
| Method | Path | Success | Errors |
|---|---|---|---|
| POST | `/accounts` `{customer_id}` | 201 | 422 |
| GET | `/accounts/{id}` → account + balance | 200 | 404 |
| POST | `/accounts/{id}/transactions` `{type, amount}` + `Idempotency-Key` header | 201 new / 200 replay | 404, 409 conflict, 422 validation / insufficient credit / overpayment |
| GET | `/accounts/{id}/transactions` | 200 | 404 |
| POST | `/transactions/{id}/complete` | 200 | 404, 409 not pending |
| POST | `/transactions/{id}/fail` | 200 | 404, 409 not pending |

Business-rule rejections use `422` with a machine-readable `code`
(`INSUFFICIENT_CREDIT`, `OVERPAYMENT`, `INVALID_AMOUNT`); conflicts use `409`
(`IDEMPOTENCY_CONFLICT`, `INVALID_STATE_TRANSITION`).

## Risks / Trade-offs
- **Hot-account contention**: creation is serialised per account. Acceptable for
  the exercise; mitigation would be a projection + optimistic concurrency.
- **Aggregation cost** grows with ledger size per account. Mitigated by the
  covering index; a materialised projection is a future extension.
- **Pending payments block further payments**: a stuck `PENDING` payment reduces
  what can be paid. Acceptable; resolution is completing or failing it.
- **No expiry of pending purchases**: reservations hold until resolved. A timeout
  sweeper is out of scope.

## Migration Plan
Greenfield. A single Alembic revision creates both tables, constraints and index.

## Open Questions
- None blocking. Possible extensions: credit balance on overpayment, reservation
  expiry, `lock_timeout` for contended accounts.
