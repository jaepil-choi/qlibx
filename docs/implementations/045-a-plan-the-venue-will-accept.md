# 045 — A plan the venue will accept

Extends `docs/implementations/044-a-plan-counts-only-money-that-will-arrive.md`. Both defects were
found by the same run — a fully-invested enhanced index — and both are the same shape: **planning
and the thing that judges planning disagreed about the same order.**

## 1. A batch that its own account cannot pay for

Planning reserves cash term by term; `Account.prepare_fill` charges it fill by fill. The two sums
are algebraically identical and **not** identical in `Decimal`. A notional on a real book already
uses all 28 significant digits, so the same money summed in a different order can differ in the
last one. Captured from the failing rebalance:

```text
cash before     3.516E-18
sell proceeds   1333510283.370090515324773564
buy required    1333510283.370090515324773570
projected      -2E-18                          <- run over
```

`prepare_fill` refuses **any** negative, correctly — an account that cannot pay for its own batch
is not a rounding opinion. A book that keeps cash never reaches this. One that declares
`cash_target = 0` — which is exactly what an enhanced index holding its ETF sleeve as a position
declares, and the whole point of records 035–040 — sits within one ulp of zero on every rebalance.

`_settle_payable` projects the batch **the way the account will**: same terms, same instrument
order, same `Decimal` operations. If the projection is negative it shaves the largest buy by whole
lots until it is not. Largest is deliberate — least disturbed in relative terms, and deterministic,
which a batch that must replay exactly requires.

The loop is bounded by `MAX_AFFORDABILITY_STEPS` and raises past it, with a separate refusal when a
sell-only batch still overdraws, which cannot be rounding and means a venue is charging more than
its declared band.

## 2. A quantity the venue then refuses

The next failure was `quantity violates listing rule for 'A267250'`, on a delta of `3.76E-7`
against a declared minimum of `1E-6`.

`TradeRule.quantize` short-circuited for a divisible listing:

```python
if self.fractional_allowed or quantity == 0:
    return quantity
```

so it enforced neither the grid (correctly — the instrument's divisibility *is* the grid) nor the
floor (incorrectly). `permits_quantity` enforces the floor for every listing, which is what record
039 established. Planning quantizes, the venue validates, and for a fractional listing the two
disagreed.

It is not a caller error. A held position sits wherever the last fills left it, so `desired - held`
is an arbitrary real number, and it lands under the floor whenever a target barely moves — which,
on a 200-name index book rebalanced daily, is most sessions on some name.

`quantize` now returns zero below the floor for a fractional listing too. That is what rounding
*toward zero* already means: below the minimum, no order is the correctly rounded size.

`tests/exchange/test_trade_rule_contract.py` asserted the old behaviour as a property —
`"quantize cannot see a minimum"`. That assertion recorded the bug rather than a contract, and is
replaced by `test_quantize_and_permits_quantity_agree_about_the_floor`, which pins what actually
has to hold: the two spellings answer the same way, on both branches.

## What this pair says

Record 039 split "is this on the unit?" from "is this big enough?" in the **validator**. Neither
this repository's tests nor its showcases noticed that the **producer** of quantities was never
given the same split, because every venue that ships trades whole shares, where the floor and the
step are the same number and the distinction is invisible.

That is the third defect in this sequence (with 005) whose common cause is a whole-share
declaration hiding a fractional one. A fractional academic venue is not an exotic configuration —
it is what alpha research runs on, because an alpha's weights are a research statement rather than
a lot a broker fills. It is worth a conformance case of its own.

## Verification

```text
uv run pytest -q                    651 passed
```

- `tests/orders/test_planning.py::test_a_fully_invested_batch_is_payable_under_the_accounts_own_arithmetic`
  carries the real failing rebalance reduced to its three largest positions, which still
  reproduces. Confirmed to **fail** with `_settle_payable` removed and pass with it.
- `tests/exchange/test_trade_rule_contract.py::test_quantize_and_permits_quantity_agree_about_the_floor`
  pins the floor agreement on both branches, and that a fractional listing still keeps every size
  above its floor exactly as given.

End to end, the enhanced-index run that could not complete one session now runs its full 2,095.
