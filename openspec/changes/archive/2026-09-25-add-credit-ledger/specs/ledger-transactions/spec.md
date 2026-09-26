## ADDED Requirements

### Requirement: Transaction types and creation
The system SHALL support creating transactions of type `DISBURSEMENT`,
`PURCHASE` and `PAYMENT` against a credit account. Every transaction SHALL be
created with status `PENDING` and SHALL record `account_id`, `idempotency_key`,
`type`, `amount`, `created_at` and `updated_at`.

#### Scenario: Create a pending disbursement
- **WHEN** a client creates a `DISBURSEMENT` of `1000.00` on an existing account
- **THEN** a transaction with status `PENDING` is persisted
- **AND** the account's `credit_granted` and `available_credit` are unchanged

#### Scenario: Unknown transaction type
- **WHEN** a client creates a transaction with type `REFUND`
- **THEN** the system rejects the request as invalid and persists nothing

### Requirement: Exact monetary amounts
Transaction amounts SHALL be exact decimals (never binary floating point),
strictly greater than zero, with at most two decimal places and at most 17
integer digits, stored as `NUMERIC(19,2)`. Amounts violating these rules MUST be
rejected, never rounded. The direction of an operation SHALL be determined by its
type, never by the sign of the amount. At the HTTP boundary amounts SHALL be
transported as JSON strings.

#### Scenario: Negative amount
- **WHEN** a client creates a `PAYMENT` with amount `-100.00`
- **THEN** the system rejects the request as an invalid amount and persists nothing

#### Scenario: Zero amount
- **WHEN** a client creates a `PURCHASE` with amount `0.00`
- **THEN** the system rejects the request as an invalid amount

#### Scenario: Too many decimal places
- **WHEN** a client creates a `PURCHASE` with amount `10.005`
- **THEN** the system rejects the request as an invalid amount instead of rounding

#### Scenario: JSON number amount
- **WHEN** an HTTP client sends `"amount": 10.1` as a JSON number
- **THEN** the API rejects the request as invalid

#### Scenario: Exact arithmetic
- **GIVEN** an account with `1.00` of completed disbursement
- **WHEN** purchases of `0.10`, `0.20` and `0.70` are created and completed
- **THEN** `outstanding_balance` is exactly `1.00` and `available_credit` is
  exactly `0.00`

### Requirement: Purchase credit reservation
The system SHALL create a `PURCHASE` only if its amount is less than or equal to
the account's `available_credit`, evaluated while holding the account lock. A
created `PENDING` purchase SHALL reserve its amount. A rejected purchase MUST NOT
persist any transaction.

#### Scenario: Purchase within available credit
- **GIVEN** an account with `available_credit = 1000.00`
- **WHEN** a purchase of `400.00` is created
- **THEN** the purchase is `PENDING`
- **AND** `reserved_credit` increases by `400.00` and `available_credit` becomes `600.00`

#### Scenario: Purchase exactly equal to available credit
- **GIVEN** an account with `available_credit = 100.00`
- **WHEN** a purchase of `100.00` is created
- **THEN** the purchase is created and `available_credit` becomes `0.00`

#### Scenario: Insufficient credit
- **GIVEN** an account with `available_credit = 100.00`
- **WHEN** a purchase of `100.01` is created
- **THEN** the system rejects it with an insufficient-credit error
- **AND** no transaction is persisted and the balance is unchanged

### Requirement: Payment overpayment protection
The system SHALL create a `PAYMENT` only if its amount is less than or equal to
`outstanding_balance − pending_payments`, evaluated while holding the account
lock. A rejected payment MUST NOT persist any transaction.

#### Scenario: Partial payment
- **GIVEN** an account with `outstanding_balance = 300.00` and no pending payments
- **WHEN** a payment of `100.00` is created
- **THEN** the payment is `PENDING` and `outstanding_balance` is still `300.00`

#### Scenario: Payment exceeding outstanding balance
- **GIVEN** an account with `outstanding_balance = 300.00`
- **WHEN** a payment of `300.01` is created
- **THEN** the system rejects it with an overpayment error and persists nothing

#### Scenario: Pending payments count against the limit
- **GIVEN** an account with `outstanding_balance = 300.00` and a `PENDING`
  payment of `250.00`
- **WHEN** a payment of `60.00` is created
- **THEN** the system rejects it with an overpayment error

#### Scenario: Payment with no debt
- **GIVEN** an account with `outstanding_balance = 0.00`
- **WHEN** any payment is created
- **THEN** the system rejects it with an overpayment error

### Requirement: Transaction state machine
The only valid status transitions SHALL be `PENDING → COMPLETED` and
`PENDING → FAILED`. `COMPLETED` and `FAILED` SHALL be terminal. Any other
transition MUST be rejected with an invalid-state-transition error that reports
the current status, and MUST NOT change the transaction.

#### Scenario: Complete a pending transaction
- **WHEN** a `PENDING` transaction is completed
- **THEN** its status becomes `COMPLETED` and `updated_at` advances

#### Scenario: Fail a completed transaction
- **GIVEN** a `COMPLETED` transaction
- **WHEN** a client attempts to fail it
- **THEN** the system rejects the request as an invalid state transition
- **AND** the transaction remains `COMPLETED`

#### Scenario: Complete a failed transaction
- **GIVEN** a `FAILED` transaction
- **WHEN** a client attempts to complete it
- **THEN** the system rejects the request as an invalid state transition

#### Scenario: Transition unknown transaction
- **WHEN** a client completes a transaction id that does not exist
- **THEN** the system returns a not-found error

### Requirement: Financial effects of transitions
Transitions SHALL have exactly these effects on the derived balance:
- `DISBURSEMENT`: `COMPLETED` increases `credit_granted` and `available_credit`
  by the amount; `PENDING` and `FAILED` have no effect.
- `PURCHASE`: `PENDING` moves the amount from available to reserved; `COMPLETED`
  moves it from reserved to outstanding (available unchanged); `FAILED` moves it
  from reserved back to available.
- `PAYMENT`: `PENDING` and `FAILED` have no effect on outstanding or available;
  `COMPLETED` decreases `outstanding_balance` and increases `available_credit` by
  the amount.
Failed transactions SHALL remain in the ledger with their original amount.

#### Scenario: Pending purchase completes
- **GIVEN** a `PENDING` purchase of `200.00` and `available_credit = 800.00`
- **WHEN** the purchase is completed
- **THEN** `reserved_credit` decreases by `200.00`, `outstanding_balance`
  increases by `200.00` and `available_credit` remains `800.00`

#### Scenario: Pending purchase fails
- **GIVEN** a `PENDING` purchase of `200.00` and `available_credit = 800.00`
- **WHEN** the purchase fails
- **THEN** `reserved_credit` decreases by `200.00` and `available_credit` becomes `1000.00`
- **AND** the purchase remains in the ledger as `FAILED` with amount `200.00`

#### Scenario: Pending payment completes
- **GIVEN** `outstanding_balance = 300.00`, `available_credit = 700.00` and a
  `PENDING` payment of `100.00`
- **WHEN** the payment is completed
- **THEN** `outstanding_balance` becomes `200.00` and `available_credit` becomes `800.00`

#### Scenario: Failed disbursement grants nothing
- **WHEN** a `PENDING` disbursement of `500.00` fails
- **THEN** `credit_granted` and `available_credit` are unchanged

### Requirement: Atomic state transitions
The system SHALL apply a transition with a single conditional update that only
matches rows whose status is `PENDING`, and SHALL treat zero affected rows as a
failed transition. A transaction's financial effect MUST be applied at most once
regardless of concurrent transition attempts.

#### Scenario: Concurrent completion of the same transaction
- **WHEN** several workers concurrently attempt to complete the same `PENDING`
  transaction
- **THEN** exactly one attempt succeeds
- **AND** every other attempt receives an invalid-state-transition error

#### Scenario: Concurrent complete and fail
- **WHEN** one worker completes and another fails the same `PENDING` transaction
  concurrently
- **THEN** exactly one of them succeeds and the final status matches the winner

### Requirement: Idempotent transaction creation
Transaction creation SHALL require an idempotency key (non-empty, at most 255
characters). The pair `(account_id, idempotency_key)` MUST be unique, enforced by
a database constraint. The idempotency lookup SHALL happen, under the account
lock, before any business-rule validation:
- if a transaction exists with the same key and the same `type` and `amount`
  (compared as decimal values), the system SHALL return it unchanged, whatever its
  current status, and SHALL NOT create another transaction;
- if a transaction exists with the same key but a different `type` or `amount`,
  the system MUST reject the request with an idempotency-conflict error and MUST
  NOT create or modify any transaction.
Requests rejected by validation or business rules persist nothing, so a later
request with the same key is evaluated afresh.

#### Scenario: Identical replay
- **WHEN** the same purchase request (key `abc`, `PURCHASE`, `100.00`) is sent twice
- **THEN** both responses reference the same transaction id
- **AND** exactly one transaction with key `abc` exists

#### Scenario: Equivalent amount representation
- **GIVEN** a transaction created with key `abc` and amount `100`
- **WHEN** a request with key `abc`, the same type and amount `100.00` is sent
- **THEN** it is treated as an identical replay

#### Scenario: Conflicting replay
- **GIVEN** a transaction created with key `abc`, `PURCHASE`, `100.00`
- **WHEN** a request with key `abc`, `PURCHASE`, `200.00` is sent
- **THEN** the system rejects it with an idempotency-conflict error
- **AND** the original transaction is unchanged and no new transaction exists

#### Scenario: Replay after credit is exhausted
- **GIVEN** a purchase created with key `abc` that consumed all available credit
- **WHEN** the identical request with key `abc` is sent again
- **THEN** the original transaction is returned instead of an insufficient-credit error

#### Scenario: Replay of a failed transaction
- **GIVEN** a transaction created with key `abc` that later became `FAILED`
- **WHEN** the identical request with key `abc` is sent again
- **THEN** the `FAILED` transaction is returned and no new transaction is created

#### Scenario: Same key on different accounts
- **WHEN** key `abc` is used on account A and on account B
- **THEN** two independent transactions are created

#### Scenario: Concurrent identical requests
- **WHEN** the same request with key `abc` is sent concurrently by several clients
- **THEN** exactly one transaction exists and every client receives its id

### Requirement: Concurrent purchases cannot oversubscribe credit
The system SHALL guarantee that concurrent purchase creations on the same account
never reserve more than the account's available credit.

#### Scenario: Two purchases competing for the last credit
- **GIVEN** an account with `credit_granted = 1000.00`, `outstanding_balance = 900.00`
  and `available_credit = 100.00`
- **WHEN** two purchases of `80.00` are created concurrently
- **THEN** exactly one is created as `PENDING` and the other is rejected with an
  insufficient-credit error
- **AND** `reserved_credit = 80.00` and `available_credit = 20.00`

#### Scenario: Many concurrent purchases
- **GIVEN** an account with `available_credit = 1000.00`
- **WHEN** 50 purchases of `30.00` are created concurrently
- **THEN** exactly 33 are created and 17 are rejected
- **AND** `available_credit = 10.00` and all account invariants hold

### Requirement: Transaction listing
The system SHALL list all transactions of an account, including `FAILED` ones,
ordered by creation time.

#### Scenario: Audit trail
- **GIVEN** an account with completed, pending and failed transactions
- **WHEN** its transactions are listed
- **THEN** every transaction is returned with its type, status and original amount
