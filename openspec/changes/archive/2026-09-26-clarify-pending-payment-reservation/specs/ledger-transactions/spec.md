## MODIFIED Requirements

### Requirement: Payment overpayment protection
The system SHALL create a `PAYMENT` only if its amount is less than or equal to
the account's `payment_capacity` (`outstanding_balance − pending_payments`),
evaluated while holding the account lock. A created `PENDING` payment SHALL
reserve its amount of payment capacity until it completes or fails, in the same way
that a pending purchase reserves credit. A rejected payment MUST NOT persist any
transaction.

#### Scenario: Partial payment
- **GIVEN** an account with `outstanding_balance = 300.00` and no pending payments
- **WHEN** a payment of `100.00` is created
- **THEN** the payment is `PENDING` and `outstanding_balance` is still `300.00`
- **AND** `payment_capacity` becomes `200.00`

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

#### Scenario: Failed payment releases its reservation
- **GIVEN** an account with `outstanding_balance = 300.00` and a `PENDING`
  payment of `250.00`
- **WHEN** that payment fails
- **THEN** `payment_capacity` returns to `300.00`
- **AND** a new payment of `300.00` can be created

### Requirement: Financial effects of transitions
Transitions SHALL have exactly these effects on the derived balance:
- `DISBURSEMENT`: `COMPLETED` increases `credit_granted` and `available_credit`
  by the amount; `PENDING` and `FAILED` have no effect.
- `PURCHASE`: `PENDING` moves the amount from available to reserved; `COMPLETED`
  moves it from reserved to outstanding (available unchanged); `FAILED` moves it
  from reserved back to available.
- `PAYMENT`: `PENDING` does not affect `outstanding_balance` or `available_credit`,
  but reserves the amount of payment capacity (`pending_payments` increases,
  `payment_capacity` decreases). `COMPLETED` uses up that reservation:
  `outstanding_balance` and `pending_payments` both decrease by the amount,
  `available_credit` increases by it, and `payment_capacity` is unchanged.
  `FAILED` releases the reservation (`pending_payments` decreases,
  `payment_capacity` increases) with no effect on `outstanding_balance` or
  `available_credit`.
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
  `PENDING` payment of `100.00` (so `payment_capacity = 200.00`)
- **WHEN** the payment is completed
- **THEN** `outstanding_balance` becomes `200.00` and `available_credit` becomes `800.00`
- **AND** `pending_payments` becomes `0.00` and `payment_capacity` remains `200.00`

#### Scenario: Pending payment fails
- **GIVEN** `outstanding_balance = 300.00`, `available_credit = 700.00` and a
  `PENDING` payment of `100.00`
- **WHEN** the payment fails
- **THEN** `outstanding_balance` remains `300.00` and `available_credit` remains `700.00`
- **AND** `pending_payments` becomes `0.00` and `payment_capacity` becomes `300.00`

#### Scenario: Failed disbursement grants nothing
- **WHEN** a `PENDING` disbursement of `500.00` fails
- **THEN** `credit_granted` and `available_credit` are unchanged
