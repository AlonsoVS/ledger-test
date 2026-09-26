# Design: Pending payments reserve payment capacity

## The symmetry
| | Purchase | Payment |
|---|---|---|
| Limited resource | available credit | payment capacity (debt not yet claimed by a payment) |
| `PENDING` | reserves credit (`reserved_credit`) | reserves capacity (`pending_payments`) |
| `COMPLETED` | reservation → outstanding debt | reservation → reduction of outstanding debt |
| `FAILED` | releases the reservation | releases the reservation |
| Checked | at creation, under the account lock | at creation, under the account lock |

## Why `payment_capacity ≥ 0` holds (replaces "pre-validated at creation")
`payment_capacity = outstanding_balance − pending_payments`. Every operation that
touches either term:
- **Payment created (`PENDING`)**: capacity decreases by `amount`. Allowed only if
  `amount ≤ payment_capacity`, checked under the account lock, so the result is ≥ 0.
- **Payment completed**: `outstanding_balance` and `pending_payments` both decrease
  by `amount`, so capacity is **unchanged**. The reservation is used up, not
  re-checked. That's why completion needs no lock and cannot overpay.
- **Payment failed**: `pending_payments` decreases, so capacity increases.
- **Purchase completed**: `outstanding_balance` increases, so capacity increases.
- **Nothing else** changes either term.

So the invariant holds after every commit. It follows that
`outstanding_balance ≥ pending_payments ≥ 0`.

This corrects the wording in the archived `add-credit-ledger/design.md` (D3, D5)
and in the README.
