# Change: Add credit account ledger

## Why
We need a minimal but rigorous ledger for a revolving credit account that can
record disbursements, purchases and partial payments, and derive the outstanding
balance and available credit exactly — including under concurrent requests and
client retries. Nothing exists yet; this change establishes the initial system.

## What Changes
- Add **credit accounts** as the concurrency boundary for credit operations
  (no stored balance).
- Add a **transaction ledger** with types `DISBURSEMENT`, `PURCHASE`, `PAYMENT`
  and statuses `PENDING`, `COMPLETED`, `FAILED` with a strict state machine
  (`PENDING → COMPLETED | FAILED`).
- Add **exact monetary handling**: positive `Decimal` amounts with at most two
  decimal places, stored as `NUMERIC(19,2)`, transported as JSON strings.
- Add **balance derivation** (credit granted, outstanding, reserved, pending
  payments, available) computed from the ledger in a single aggregate query.
- Add **credit reservation** for purchases: a purchase is only created if the
  amount fits in available credit, checked under an account row lock.
- Add **overpayment protection**: a payment is only created if the amount fits in
  `outstanding_balance − pending_payments`, checked under the same lock.
  *(Refinement over the original specification, which left this undefined.)*
- Add **idempotent creation** keyed by `(account_id, idempotency_key)`: identical
  replays return the existing transaction; mismatched replays are rejected.
- Add **atomic state transitions** via conditional `UPDATE ... WHERE status =
  'PENDING'`, so a transaction's effect is applied at most once.
- Add a thin **FastAPI** HTTP layer over the service layer.
- Add a PostgreSQL-backed test suite covering lifecycle, failure, idempotency and
  concurrency scenarios, asserting credit conservation throughout.

## Impact
- Affected specs (all new):
  - `credit-accounts`
  - `ledger-transactions`
  - `account-balance`
- Affected code (all new): `src/ledger/` (domain, repository, service, api),
  `migrations/`, `tests/`, `docker-compose.yml`, `pyproject.toml`.
- Out of scope: interest, fees, multi-currency, customer management,
  authentication/authorization, external payment providers, async processing,
  balance projections, account closure/delinquency, double-entry accounting.
