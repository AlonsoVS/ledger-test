# Credit Ledger — Specification

> Source specification for the exercise. The OpenSpec specs in
> `openspec/specs/` are authoritative; refinements made during
> design review are summarised in [Amendments](#16-amendments-design-review).

## 1. Problem

Implement a simple ledger for a credit account.

The system must support:

* Initial and subsequent credit disbursements.
* Purchases against the available credit.
* Partial payments.
* Calculation of outstanding balance.
* Calculation of available credit.
* Idempotent transaction creation.
* Safe concurrent operations on the same credit account.
* Exact monetary arithmetic without floating-point types.

The implementation should prioritize correctness, consistency, and clear domain rules over feature completeness.

Interest calculation is intentionally out of scope for the initial implementation.

---

## 2. Assumptions and Scope

The credit product is modeled as a revolving credit facility.

A `DISBURSEMENT` increases the total credit granted to the account. A `PURCHASE` consumes part of that credit and creates outstanding debt. A `PAYMENT` reduces the outstanding debt and therefore releases available credit.

The system does not transfer actual money as part of this exercise. Transactions represent the financial events that affect the state of the credit account.

The ledger is the authoritative source of financial state. No mutable account balance is maintained as a source of truth.

For this exercise, the following are explicitly out of scope:

* Interest calculation.
* Fees.
* Multiple currencies.
* Customer management.
* Authentication and authorization.
* External payment providers.
* Asynchronous event processing.
* Balance projections/materialized views.
* Account closure or delinquency states.

---

# 3. Domain Model

## 3.1 Credit Account

A `CreditAccount` represents a customer's revolving credit facility.

```text
CreditAccount
-------------
id
customer_id
created_at
updated_at
```

The account acts as the **concurrency boundary** for operations that reserve credit.

It does not store `available_credit`, `outstanding_balance`, or another mutable balance as a source of truth.

---

## 3.2 Transaction

A transaction represents a financial operation affecting a credit account.

```text
Transaction
-----------
id
account_id
idempotency_key
type
status
amount
created_at
updated_at
```

### Transaction types

```text
DISBURSEMENT
PURCHASE
PAYMENT
```

### Transaction statuses

```text
PENDING
COMPLETED
FAILED
```

`COMPLETED` and `FAILED` are terminal states.

The only valid state transitions are:

```text
PENDING → COMPLETED
PENDING → FAILED
```

No transition is allowed from a terminal state.

---

# 4. Monetary Representation

All monetary values are represented using fixed-point decimal arithmetic.

The database uses:

```text
NUMERIC(19,2)
```

Floating-point types such as `float` or `double` are not used for monetary values because most decimal fractions cannot be represented exactly using binary floating-point arithmetic.

For this exercise, amounts are restricted to two decimal places.

Transaction amounts must always be positive:

```text
amount > 0
```

The semantic direction of an operation is determined by its transaction type rather than by a negative amount.

For example:

```text
PAYMENT 100.00
```

is valid, while:

```text
PAYMENT -100.00
```

is invalid.

---

# 5. Financial Model

The ledger derives the account state from its transactions.

## 5.1 Credit Granted

```text
credit_granted =
    SUM(amount)
    WHERE type = DISBURSEMENT
    AND status = COMPLETED
```

Pending and failed disbursements do not increase the granted credit.

---

## 5.2 Outstanding Balance

```text
outstanding_balance =
      SUM(PURCHASE amount WHERE status = COMPLETED)
    - SUM(PAYMENT amount WHERE status = COMPLETED)
```

A pending or failed payment does not reduce the outstanding balance.

A pending purchase is not yet part of the outstanding balance.

---

## 5.3 Reserved Credit

Pending purchases reserve available credit:

```text
reserved_credit =
    SUM(amount)
    WHERE type = PURCHASE
    AND status = PENDING
```

---

## 5.4 Available Credit

```text
available_credit =
    credit_granted
    - outstanding_balance
    - reserved_credit
```

The system must never allow:

```text
available_credit < 0
```

---

# 6. Fundamental Invariants

The following invariants must hold for every account.

### 6.1 Credit conservation

```text
credit_granted =
    available_credit
    + outstanding_balance
    + reserved_credit
```

This represents the complete allocation of the credit granted to the account.

Every unit of granted credit must be in exactly one of these states:

* available;
* outstanding;
* reserved.

---

### 6.2 No negative available credit

```text
available_credit >= 0
```

A purchase may only be created as `PENDING` when sufficient available credit exists.

---

### 6.3 Positive transaction amounts

```text
amount > 0
```

---

### 6.4 Terminal states cannot transition

Once a transaction reaches `COMPLETED` or `FAILED`, it cannot change state.

---

### 6.5 Idempotency

The pair:

```text
(account_id, idempotency_key)
```

must be unique.

A repeated request with the same account and idempotency key represents the same operation.

If the repeated request contains the same transaction parameters, the existing transaction should be returned/reused.

If the idempotency key is reused with different parameters, the request must be rejected as a conflict.

---

# 7. Transaction Lifecycle

## 7.1 Disbursement

### PENDING

No financial effect:

```text
credit_granted: unchanged
available_credit: unchanged
```

### COMPLETED

```text
credit_granted += amount
available_credit += amount
```

### FAILED

No financial effect.

---

## 7.2 Purchase

A purchase requires an availability check before creation. *(Amended by R1: payments
require an equivalent payment-capacity check; see §7.3.)*

### PENDING

The purchase reserves credit:

```text
reserved_credit += amount
available_credit -= amount
```

### COMPLETED

The reservation becomes outstanding debt:

```text
reserved_credit -= amount
outstanding_balance += amount
```

The available credit does not change during this transition.

### FAILED

The reservation is released:

```text
reserved_credit -= amount
available_credit += amount
```

---

## 7.3 Payment

*(Amended by R1.)* A payment requires a payment-capacity check before creation,
mirroring the purchase availability check:

```text
payment_capacity = outstanding_balance - pending_payments
amount <= payment_capacity
```

### PENDING

A pending payment does not affect `outstanding_balance` or `available_credit`, but
it reserves payment capacity, reducing the outstanding debt that later pending
payments can claim:

```text
outstanding_balance: unchanged
available_credit: unchanged
pending_payments += amount
payment_capacity -= amount
```

### COMPLETED

The payment reduces outstanding debt and uses up its reservation:

```text
outstanding_balance -= amount
available_credit += amount
pending_payments -= amount
payment_capacity: unchanged
```

### FAILED

No effect on `outstanding_balance` or `available_credit`; the reservation is released:

```text
pending_payments -= amount
payment_capacity += amount
```

---

# 8. Concurrency

## 8.1 Problem

Two purchases may arrive concurrently for the same account.

For example:

```text
credit_granted = 1000
outstanding = 900
reserved = 0
available = 100
```

Two purchases arrive:

```text
PURCHASE A = 80
PURCHASE B = 80
```

Both requests must not independently observe `available = 100` and then reserve credit.

Only one purchase may successfully reserve the available credit.

The order in which concurrent operations are serialized is not semantically important. What matters is that the final state always satisfies the account invariants.

---

## 8.2 Concurrency Strategy

The account row is used as the serialization boundary for credit reservations.

When creating a purchase:

```text
BEGIN TRANSACTION

SELECT credit_account
FROM credit_accounts
WHERE id = ?
FOR UPDATE

calculate available credit

if available credit < purchase amount:
    reject

create PENDING purchase

COMMIT
```

The row-level lock prevents another concurrent purchase for the same account from performing the availability check and reservation simultaneously.

Purchases for different accounts remain independent and can execute concurrently.

---

## 8.3 Why pessimistic locking?

Pessimistic locking was selected because the critical section is small and the conflict domain is naturally the credit account.

The account does not store the balance. The lock exists only to provide a serialization point for operations that compete for the same available credit.

This allows the system to keep the transaction ledger as the source of truth while still enforcing the invariant that available credit cannot become negative.

Optimistic locking was considered, but it would require introducing a version or another mutable coordination mechanism on the account without providing a clear advantage for this small workload.

Serializable transactions were also considered. They could provide the required isolation, but explicit account-level locking makes the intended concurrency boundary more visible and easier to reason about for this exercise.

---

# 9. Transaction State Concurrency

State transitions use an atomic conditional update.

For example:

```sql
UPDATE transactions
SET status = 'COMPLETED'
WHERE id = ?
  AND status = 'PENDING';
```

The application checks the number of affected rows.

If one row was updated, the transition succeeded.

If zero rows were updated, the transaction was no longer `PENDING` and the transition must not be applied again.

This prevents two concurrent workers from both successfully transitioning the same transaction.

This mechanism is separate from account-level locking because it solves a different concurrency problem.

---

# 10. Idempotency

Transaction creation requires an idempotency key.

The database enforces:

```text
UNIQUE(account_id, idempotency_key)
```

The application first attempts to create the transaction.

If an existing transaction with the same key is found:

### Same request

If the relevant parameters match:

```text
account_id
type
amount
```

the existing transaction is returned.

### Conflicting request

If the parameters differ, the request is rejected as a conflict.

Example:

```text
First request:
key = abc
type = PURCHASE
amount = 100
```

followed by:

```text
key = abc
type = PURCHASE
amount = 200
```

must not create or modify a transaction.

---

# 11. Failure Handling

Failed transactions remain in the ledger for auditability.

A failed transaction does not contribute to the financial calculations.

For a failed purchase that previously reserved credit, the transition from `PENDING` to `FAILED` releases the reservation.

No separate mutation of the transaction amount is required.

The original transaction amount remains available for historical/audit purposes while its `FAILED` status causes it to have no financial effect.

---

# 12. Important Scenarios

The implementation must cover at least the following cases.

### Basic lifecycle

* Create a credit account.
* Complete a disbursement.
* Create a purchase within available credit.
* Complete the purchase.
* Complete a partial payment.
* Verify outstanding and available credit.

### Insufficient credit

* Attempt a purchase greater than available credit.
* Verify that no pending transaction is created.

### Pending purchase

* Create a pending purchase.
* Verify that available credit decreases.
* Complete it.
* Verify that the amount moves from reserved to outstanding.

### Failed purchase

* Create a pending purchase.
* Fail it.
* Verify that the reservation is released.

### Pending payment

* Create a pending payment.
* Verify that outstanding balance does not change.
* Complete it.
* Verify that available credit increases.

### Idempotency

* Repeat an identical request.
* Verify that only one transaction exists.
* Reuse the key with different parameters.
* Verify that the request is rejected.

### Concurrent purchases

* Start two purchases concurrently against the same account.
* Verify that the combined reserved credit never exceeds the available credit.
* Verify that the account invariants remain valid.

### Concurrent state transitions

* Attempt to complete the same transaction concurrently from multiple workers.
* Verify that only one transition succeeds.

---

# 13. Trade-offs

## Ledger as source of truth

The system does not maintain a mutable balance.

### Advantages

* Avoids multiple sources of truth.
* Makes the financial history auditable.
* Makes transaction effects explicit.
* Simplifies correctness reasoning for a small ledger.

### Trade-off

Calculating the account state requires aggregating transactions. At larger scale, this could become expensive.

A future implementation could introduce a materialized balance projection while keeping the ledger as the authoritative source.

---

## Simplified ledger vs. double-entry accounting

This implementation uses a **simplified account ledger**, not a full double-entry accounting system.

A real double-entry ledger would represent each financial event as balanced debit/credit entries across accounts.

That level of accounting is outside the scope of this exercise because the problem only requires tracking the state of a single credit account.

The simplified model is sufficient to represent:

```text
credit granted
outstanding debt
reserved credit
available credit
```

without introducing additional accounting entities that do not contribute to the requirements being evaluated.

---

## Pessimistic locking

Account-level pessimistic locking provides a clear serialization boundary for competing credit reservations.

The trade-off is that concurrent operations against the same account are serialized, potentially limiting throughput for a highly contended account.

For the scope of this exercise, correctness and clear consistency guarantees take precedence over optimizing for extremely high contention.

---

# 14. Non-Goals

The implementation will intentionally not include:

* Interest calculation.
* Fees.
* Double-entry accounting.
* Multiple currencies.
* Distributed transactions.
* Event streaming.
* External payment providers.
* Authentication.
* Authorization.
* Balance caching or materialized projections.
* Advanced retry infrastructure.
* Account lifecycle management.

These could be considered extensions in a production system but are outside the scope of the exercise.

---

# 15. Success Criteria

The implementation is considered correct when:

1. All supported transaction types follow the defined state machine.
2. Monetary values use exact decimal arithmetic.
3. Available credit can never become negative.
4. Credit conservation remains true after every valid state transition.
5. Duplicate requests do not create duplicate transactions.
6. Conflicting reuse of an idempotency key is rejected.
7. Concurrent purchases cannot oversubscribe available credit.
8. Concurrent state transitions cannot apply the same transaction effect more than once.
9. Failed transactions remain auditable without affecting financial calculations.
10. The implementation and tests clearly demonstrate the reasoning behind these decisions.

---

# 16. Amendments (design review)

Details and rationale in `openspec/changes/archive/2026-09-25-add-credit-ledger/design.md`.

* **R1 — Overpayment protection / payment-capacity reservation.** A payment is
  created only if `amount ≤ payment_capacity`, where
  `payment_capacity = outstanding_balance − pending_payments` (checked under the
  account lock). A pending payment therefore **reserves payment capacity**, just as a
  pending purchase reserves credit. The reservation is used up on completion and
  released on failure (§7.3). Creation establishes `payment_capacity ≥ 0`. Completion
  preserves it, because outstanding and pending payments fall by the same amount, and
  nothing else can reduce it. This guarantees `outstanding_balance ≥ 0` and
  `available_credit ≤ credit_granted`. Supersedes §7.2 "a purchase is the only
  transaction type that requires an availability check" and the original §7.3
  "PENDING: no financial effect". Clarified by the OpenSpec change
  `clarify-pending-payment-reservation`.
* **R2 — Single-statement balance.** All balance quantities are computed in one
  aggregate query so they share a snapshot under `READ COMMITTED`.
* **R3 — Idempotency ordering and locking.** All transaction creation (not only
  purchases) takes the account lock; the idempotency lookup runs before business
  validation, so retries of a successful request return the original transaction
  even if credit has since been exhausted. Replays return the existing
  transaction whatever its status. Rejected requests persist nothing. The unique
  constraint remains as a backstop. Refines §10 "the application first attempts
  to create the transaction".
* **R4 — Money at the boundary.** Amounts with more than two decimals are
  rejected, never rounded. HTTP amounts are JSON strings; JSON numbers are
  rejected.
* **Transitions on non-pending transactions** are reported as an
  invalid-state-transition error (not a silent no-op).
