# Change: Clarify that pending payments reserve payment capacity

## Why
Code review noticed that the implementation and the specification no longer tell
exactly the same story. The source spec says a `PENDING` payment has "no financial
effect", but the overpayment rule added in `add-credit-ledger` (R1) counts pending
payments against the next payment. In practice a pending payment therefore
**reserves payment capacity**, just as a pending purchase reserves credit.

The previous justification, "payment completion was pre-validated at creation",
was also imprecise. The condition is not just checked once. The reservation made
at creation keeps it true until the payment completes or fails.

## What Changes
- Name the derived quantity `payment_capacity = outstanding_balance − pending_payments`
  and list it in the balance derivation.
- State the effects of each payment status explicitly:
  - `PENDING` leaves `outstanding_balance` and `available_credit` unchanged, but
    reserves payment capacity.
  - `COMPLETED` uses up the reservation: outstanding drops by the same amount as
    pending payments, so `payment_capacity` is unchanged.
  - `FAILED` releases the reservation.
- Restate the invariant as `payment_capacity ≥ 0`, and explain why it holds.
- Align code vocabulary: `Balance.payable_amount` → `Balance.payment_capacity`,
  the `Overpayment` error wording, and `payment_capacity` exposed in the balance API.
- Update `docs/credit-ledger-spec.md` §7.3 and README wording.

No change to which operations are accepted or rejected.

## Impact
- Affected specs: `ledger-transactions` (MODIFIED: Payment overpayment protection,
  Financial effects of transitions), `account-balance` (MODIFIED: Balance derivation,
  Account invariants).
- Affected code: `domain/balance.py`, `domain/rules.py`, `domain/errors.py`,
  `api/schemas.py`, related tests; docs only otherwise.
