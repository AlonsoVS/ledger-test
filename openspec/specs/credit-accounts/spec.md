# credit-accounts Specification

## Purpose
Define the credit account: a revolving credit facility that stores no balance and acts as the concurrency boundary (row lock) for all transaction creation on it.

## Requirements

### Requirement: Credit account creation
The system SHALL create a credit account for a given `customer_id`, assigning a
unique identifier and creation/update timestamps. A newly created account SHALL
have zero credit granted, zero outstanding balance, zero reserved credit and zero
available credit.

#### Scenario: Create an account
- **WHEN** a client creates an account with `customer_id = "cust-1"`
- **THEN** the system returns a new account with a unique `id`
- **AND** its balance reports `credit_granted = 0.00`, `outstanding_balance = 0.00`,
  `reserved_credit = 0.00` and `available_credit = 0.00`

#### Scenario: Missing customer id
- **WHEN** a client creates an account without a `customer_id`
- **THEN** the system rejects the request as invalid and creates no account

### Requirement: No stored balance
The credit account SHALL NOT store any balance (credit granted, outstanding,
reserved or available) as a source of truth. All balances MUST be derived from
the account's transactions.

#### Scenario: Balance reflects ledger only
- **WHEN** the balance of an account is requested
- **THEN** every reported quantity is computed from the account's transactions

### Requirement: Account as concurrency boundary
The system SHALL use the credit account row as the serialization point for all
transaction creation on that account, by acquiring a row-level exclusive lock
(`SELECT ... FOR UPDATE`) before evaluating balances or idempotency. Operations on
different accounts SHALL NOT block each other.

#### Scenario: Creations on the same account are serialized
- **WHEN** two transaction-creation requests for the same account run concurrently
- **THEN** the second one evaluates balances only after the first has committed
  or rolled back

#### Scenario: Different accounts proceed independently
- **WHEN** transaction-creation requests run concurrently for two different accounts
- **THEN** neither request waits on the other's lock

### Requirement: Unknown account
The system SHALL reject any operation that references a non-existent account
with a not-found error and persist nothing.

#### Scenario: Transaction for unknown account
- **WHEN** a client creates a transaction for an account id that does not exist
- **THEN** the system returns a not-found error
- **AND** no transaction is created
