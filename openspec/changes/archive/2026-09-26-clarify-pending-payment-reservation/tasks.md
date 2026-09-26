## 1. Specification
- [x] 1.1 MODIFIED requirements in `ledger-transactions` and `account-balance`
- [x] 1.2 Update `docs/credit-ledger-spec.md` §7.2, §7.3 and amendment R1
- [x] 1.3 Update README and `openspec/project.md` wording

## 2. Code alignment (no behavior change)
- [x] 2.1 Rename `Balance.payable_amount` → `payment_capacity`; update rule, error and invariant messages
- [x] 2.2 Expose `payment_capacity` in the balance API response
- [x] 2.3 Tests: failed payment releases capacity; completion leaves capacity unchanged
- [x] 2.4 `make check` passes; `openspec validate --strict` passes
