## MODIFIED Requirements

### Requirement: Balance derivation
The system SHALL derive an account's balance from its transactions as follows:
- `credit_granted` = sum of `COMPLETED` `DISBURSEMENT` amounts
- `outstanding_balance` = sum of `COMPLETED` `PURCHASE` amounts minus sum of
  `COMPLETED` `PAYMENT` amounts
- `reserved_credit` = sum of `PENDING` `PURCHASE` amounts
- `pending_payments` = sum of `PENDING` `PAYMENT` amounts (payment capacity
  reserved by pending payments)
- `available_credit` = `credit_granted − outstanding_balance − reserved_credit`
- `payment_capacity` = `outstanding_balance − pending_payments` (outstanding debt
  not yet claimed by a pending payment)

`FAILED` transactions MUST NOT contribute to any quantity. Empty sums SHALL be
`0.00`. All quantities SHALL be exact decimals with two decimal places.

#### Scenario: Basic lifecycle
- **GIVEN** a new account
- **WHEN** a disbursement of `1000.00` is completed
- **AND** a purchase of `300.00` is created and completed
- **AND** a payment of `120.50` is created and completed
- **THEN** the balance reports `credit_granted = 1000.00`,
  `outstanding_balance = 179.50`, `reserved_credit = 0.00`,
  `pending_payments = 0.00`, `available_credit = 820.50` and
  `payment_capacity = 179.50`

#### Scenario: Pending payment reserves payment capacity only
- **GIVEN** an account with `outstanding_balance = 300.00` and `available_credit = 700.00`
- **WHEN** a payment of `100.00` is created and left `PENDING`
- **THEN** `outstanding_balance` is still `300.00` and `available_credit` is still `700.00`
- **AND** `pending_payments = 100.00` and `payment_capacity = 200.00`

#### Scenario: Failed transactions are ignored
- **GIVEN** an account with a `FAILED` disbursement, a `FAILED` purchase and a
  `FAILED` payment
- **WHEN** the balance is requested
- **THEN** none of those amounts appear in any balance quantity
- **AND** the failed transactions are still listed in the account's ledger

### Requirement: Account invariants
For every account, after every committed operation, the system SHALL maintain:
- credit conservation: `credit_granted = available_credit + outstanding_balance +
  reserved_credit`
- `available_credit ≥ 0`
- `outstanding_balance ≥ 0`
- `payment_capacity ≥ 0`, i.e. pending payments never claim more than the
  outstanding debt

`payment_capacity ≥ 0` is established when a payment is created, which requires
the account lock and `amount ≤ payment_capacity`. It is preserved afterwards: completing a payment lowers
`outstanding_balance` and `pending_payments` by the same amount, failing a payment
or completing a purchase only increases capacity, and no other operation changes it.

#### Scenario: Invariants after a mixed sequence
- **WHEN** any sequence of valid creations and state transitions has been applied
  to an account
- **THEN** all four invariants hold for its balance

#### Scenario: Invariants after concurrent operations
- **WHEN** many purchases and payments are created and transitioned concurrently
  on one account
- **THEN** all four invariants hold once every operation has finished
