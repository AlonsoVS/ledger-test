## 1. Project scaffolding
- [x] 1.1 Initialise `uv` project (Python 3.12), `src/ledger` package layout, `pyproject.toml`
- [x] 1.2 Add dependencies: fastapi, uvicorn, sqlalchemy>=2, psycopg[binary]>=3, alembic, pydantic>=2; dev: pytest, httpx, ruff, mypy
- [x] 1.3 Add `docker-compose.yml` with PostgreSQL 16 (app DB + test DB) and `.env.example`
- [x] 1.4 Configure ruff, mypy (strict) and pytest; add `Makefile` targets (`up`, `migrate`, `test`, `lint`, `run`)

## 2. Domain layer (pure, no I/O)
- [x] 2.1 `enums.py`: `TransactionType`, `TransactionStatus`
- [x] 2.2 `money.py`: `parse_amount` (reject non-finite, ≤ 0, > 2 decimals, > 17 integer digits; quantize to 0.01)
- [x] 2.3 `errors.py`: `AccountNotFound`, `TransactionNotFound`, `InvalidAmount`, `InsufficientCredit`, `Overpayment`, `IdempotencyConflict`, `InvalidStateTransition`
- [x] 2.4 `balance.py`: `Balance` value object (with derived `available_credit`) and invariant checker
- [x] 2.5 `state.py`: allowed transitions table
- [x] 2.6 Unit tests for 2.2–2.5

## 3. Persistence
- [x] 3.1 SQLAlchemy models for `credit_accounts` and `transactions` (Numeric(19,2), CHECK constraints, unique key, covering index)
- [x] 3.2 Alembic initial migration
- [x] 3.3 Repository: `lock_account` (FOR UPDATE), `get_account`, `find_by_idempotency_key`, `insert_transaction`, `transition` (conditional UPDATE ... RETURNING), `get_balance` (single FILTER aggregate), `list_transactions`

## 4. Service layer
- [x] 4.1 `create_account`
- [x] 4.2 `create_transaction`: lock → idempotency lookup → balance → type rule (purchase ≤ available, payment ≤ outstanding − pending_payments) → insert; IntegrityError fallback re-lookup
- [x] 4.3 `complete_transaction` / `fail_transaction` via conditional update; distinguish not-found vs invalid transition
- [x] 4.4 `get_balance`, `list_transactions`

## 5. HTTP API
- [x] 5.1 Pydantic schemas with string-only amounts (reject JSON numbers)
- [x] 5.2 Routes per design D8; `Idempotency-Key` header; 201 vs 200 on replay
- [x] 5.3 Exception → HTTP mapping with machine-readable `code`

## 6. Tests (PostgreSQL)
- [x] 6.1 Fixtures: per-test clean DB, session factory, `assert_invariants(account_id)` helper
- [x] 6.2 Basic lifecycle (disburse → purchase → complete → partial payment → balances)
- [x] 6.3 Insufficient credit (no transaction persisted); exact-boundary purchase
- [x] 6.4 Pending/complete/fail purchase effects
- [x] 6.5 Pending/complete payment effects; overpayment rejections incl. pending payments
- [x] 6.6 Failed transactions remain listed and excluded from balances
- [x] 6.7 Idempotency: identical replay, `100` vs `100.00`, conflict, replay after exhaustion, replay of FAILED, cross-account key
- [x] 6.8 Concurrency: two purchases for last credit; 50 purchases of 30.00 over 1000.00 (barrier-synchronised threads, separate connections)
- [x] 6.9 Concurrency: N workers completing the same transaction → exactly one success; complete vs fail race
- [x] 6.10 Concurrency: identical idempotent requests in parallel → one transaction
- [x] 6.11 Mixed concurrent workload (purchases, payments, transitions) → invariants hold
- [x] 6.12 API tests: status codes, string amounts, JSON-number rejection

## 7. Documentation
- [x] 7.1 README: setup, running, API examples, design summary and trade-offs (link to design.md)
- [x] 7.2 Validate the change with `openspec validate add-credit-ledger --strict`
- [x] 7.3 Archive the change into `openspec/specs/` after implementation
