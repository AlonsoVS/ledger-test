# Project Context

## Purpose
A small, correctness-focused ledger for a revolving credit account. It supports
credit disbursements, purchases against available credit, partial payments, and
derivation of outstanding balance and available credit from an append-only
transaction ledger. It is scoped as a technical exercise: correctness,
consistency and clear domain rules take priority over feature breadth.

## Tech Stack
- Python 3.12 (managed with `uv`)
- PostgreSQL 16 (via `docker compose`) — required for `SELECT ... FOR UPDATE`
- SQLAlchemy 2.0 (typed ORM + Core) with psycopg 3
- Alembic for schema migrations
- FastAPI + Pydantic v2 for a thin HTTP layer
- pytest for unit, integration and concurrency tests
- ruff (lint + format) and mypy (strict) for static checks

## Project Conventions

### Code Style
- Type hints everywhere; `mypy --strict` must pass.
- `ruff format` + `ruff check` are the formatting/lint authority.
- Monetary values are always `decimal.Decimal`; `float` MUST NOT appear in any
  code path that touches money (including JSON parsing and serialization).
- Domain errors are explicit exception classes, mapped to HTTP status codes only
  at the API boundary.

### Architecture Patterns
- Layered: `domain` (pure rules, no I/O) → `service` (use cases, transaction
  boundaries, locking) → `repository` (SQL) → `api` (HTTP mapping only).
- The ledger (`transactions` table) is the single source of truth. No mutable
  balance column exists anywhere.
- Every write use case runs inside exactly one database transaction owned by the
  service layer.
- The `credit_accounts` row is the concurrency boundary for transaction creation.

### Testing Strategy
- Unit tests for pure domain logic (money validation, balance math, state machine).
- Integration tests for service use cases against a real PostgreSQL.
- Concurrency tests using real threads with independent DB connections and a
  `threading.Barrier`, run against PostgreSQL (never mocked).
- Every integration test asserts the credit-conservation invariant at the end.
- A thin set of API tests verifies HTTP mapping (status codes, string amounts).

### Git Workflow
- Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
- One OpenSpec change per feature; archive the change after implementation.

## Domain Context
- **DISBURSEMENT** increases credit granted.
- **PURCHASE** consumes credit: reserves it while `PENDING`, becomes outstanding
  debt when `COMPLETED`, releases the reservation when `FAILED`.
- **PAYMENT** reduces outstanding debt when `COMPLETED`.
- Derived quantities (completed/pending sums per type):
  - `credit_granted = Σ DISBURSEMENT[COMPLETED]`
  - `outstanding_balance = Σ PURCHASE[COMPLETED] − Σ PAYMENT[COMPLETED]`
  - `reserved_credit = Σ PURCHASE[PENDING]`
  - `pending_payments = Σ PAYMENT[PENDING]`
  - `available_credit = credit_granted − outstanding_balance − reserved_credit`
- Invariants: `available_credit ≥ 0`, `outstanding_balance ≥ 0`,
  `outstanding_balance − pending_payments ≥ 0`, amounts `> 0`, terminal states
  are immutable, `(account_id, idempotency_key)` is unique.

## Important Constraints
- Exact decimal arithmetic, 2 decimal places, `NUMERIC(19,2)` in the database.
- Amounts with more than 2 decimal places are rejected, never rounded.
- Single currency; no interest, fees, customers, auth, or account lifecycle.

## External Dependencies
- None beyond PostgreSQL. No payment providers or message brokers.
