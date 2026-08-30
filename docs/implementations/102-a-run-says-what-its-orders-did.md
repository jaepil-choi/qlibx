# 102 — A run says what its orders did, and both envelope fields read the result's real shape

**Closes:** `docs/issues/039-nothing-reports-the-gap-between-the-declared-book-and-the-realised-one.md`
(owner-approved 2026-08-31), and `docs/issues/041`, which the work found.
**Branch:** `fix/039-a-run-says-what-its-orders-did`.

## Why this change exists

A market-neutral run reported `{"ok": true, "occurrences": 732, "account_version": 244}`. Its long
side landed on 0.500 at every rebalance across a year; its short side never did, and by December the
book carried **+9.1% of NAV in unintended net long exposure**. A strategy whose entire premise is
neutrality was running a material directional bet.

Nothing was broken. Names were not tradable at the fill instant, the venue said so, and every one of
those 1,481 fills recorded `reason: nontradable` in `vqapr.fill` — 3.1% of 47,318 rows. **Nothing
aggregated them**, so the run's own reporting could not distinguish that from a clean run.

> `ok: true` on this run means "the simulation executed", and I had been reading it as "the book I
> declared is the book that was held". Those differ by nine percent of NAV.

The follow-up is what makes it a reporting defect rather than a market fact. Most of the drift was a
bug in the reporter's own model — degenerate frozen-price listings — and the signal that would have
exposed it on day one was a 3.1% zero-dealt rate against a 1.2% baseline. They found it by accident
two hours later.

## What changed

`run.complete` carries `fills`:

```json
"fills": {"orders": 47318, "dealt": 45834, "partial": 1404, "zero_dealt": 1484,
          "reasons": {"no_trade": 3, "nontradable": 1481}}
```

- **`orders`** is every row the venue answered, so the three counts are readable as shares of it
  rather than as bare magnitudes.
- **`partial`** is an order that dealt something but less than requested. Same declared-versus-
  realised gap, one degree quieter, and it was 1,404 of that run's short requests.
- **`reasons` stays a mapping, not a total.** `absent`, `nontradable` and `no_trade` are facts about
  the market; `unfunded` is a fact about the account. `ZeroDealtReason`'s own docstring separates
  them for that reason, and a reader asking what the market refused them must not be handed their
  own empty purse in the same number.

Reported on the success path deliberately: the run is legitimate, and what is worth saying is what
it managed to trade.

## What this change found: `docs/issues/024`'s fix never reached production

`_tables_declared` — record `094`'s fix for `docs/issues/024` — read `result.tables`.

**`SimulationResult` has no `tables` attribute.** Its two fields are `occurrences` and `final_state`;
the rows live at `final_state.recorder_rows`. So the component-declared half of that fix returned
`{}` on every real run, which is exactly the defect 024 filed, while its unit test passed a
`SimpleNamespace(tables={...})` and stayed green for a week.

Both fields now read one helper, `_recorded`, so they cannot drift apart again, and the new test
pins the attribute path against the **real types** rather than against a double:

```python
fields = {field.name for field in dataclasses.fields(SimulationResult)}
assert "final_state" in fields
assert "tables" not in fields
assert isinstance(AcceptedRunState.recorder_rows, property)
```

The lesson is filed separately as `docs/issues/041`, because the class matters more than the
instance: **a test double that does not have the real object's shape proves the code works against
the double.** This is the third variant of the same family in two weeks — a boundary in prose
(`028`), an invariant in a docstring (the materialization refusal), and now a verification against a
stand-in.

## Validation

| check | result |
|---|---|
| `tests/cli/test_the_run_reports_what_its_orders_did.py` (new) | 7 passed |
| `tests/cli/test_a_run_reports_the_tables_it_declared.py` (double corrected) | 5 passed |
| `tests/cli/` | 205 passed |
| fast suite | **1446 passed**, 14 deselected |
| `ruff check src tests` | 14 findings, all pre-existing |

**Proven end to end, not only in units.** `test_run_executes_a_declared_spec_end_to_end` now pins
the envelope a real three-day run produces — `orders: 2, dealt: 1, zero_dealt: 1, reasons:
{no_trade: 1}` — which is also the assertion that would have failed against the old
`result.tables` path, since it exercises the same helper through the same run.

Baseline regeneration was a pure line shift.
