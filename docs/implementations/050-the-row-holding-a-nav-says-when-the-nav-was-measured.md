# 050 — The row holding a nav says when the nav was measured

`_record_defaults` wrote the account-level row of `vqapr.account` with `observed_at` hard-coded to
`None`, while the instrument rows written in the same callback carried it. So the one row that
holds `nav` did not say which instant that `nav` belongs to.

## Why that matters

The record is deliberately **offset one commit behind the callback that writes it** — the account
row stamped at callback T carries the mark committed at T-1's execution instant. That offset is
correct and load-bearing: a callback must record the account it saw *before* deciding, or a later
run replaying the record would be reading its own future. It is what prevents a look-ahead.

But it means `available_at` and the instant the `nav` was measured are two different times, and
canon already fixes that they stay two columns (PRD 9.4, restated in `publish_run_record`). With
`observed_at` empty on the account row, a reader had two options and both are bad:

- **join back** to the same callback's instrument rows and take their `observed_at` — which has
  nothing to join to across any span where the book held no positions, and needs a reader to know
  the offset exists before they would think to do it;
- **date the series by `available_at`** — which silently labels every value one occurrence late.

The second is what an outside build actually did. Measured, that mislabelling took a factor
return's correlation against its published reference from **0.929 to 0.017**. No error was raised
anywhere; the series was simply wrong, and only collapsed far enough to be obvious by luck. Had
the cadence been closer, it would have produced a plausible number.

## What changed

One value. `nav` and `marked_at` come from the same `mark` object three lines above, so the row
now carries the instant its own `nav` was measured:

```python
"observed_at": None if mark is None else mark.marked_at,
```

`marked_at` is the right field rather than a per-instrument time: this row is account-level, it
has no instrument axis, and `account/history.py` already treats `marked_at` as the fallback when a
per-instrument `observed_at` is absent. `None` when there is no mark yet, unchanged.

## Trade-off

This changes the values in a **published column** — account rows that previously read `NULL` now
carry a timestamp. Nothing that read the column can break, because the previous value was
unconditionally absent, and the instrument rows are untouched. A consumer that filtered on
`observed_at IS NULL` to isolate account rows would now need `instrument = '_ACCOUNT'`, which is
the identity the canon fixes for that purpose and the correct predicate either way.

Not attempted here: making the offset harder to misread in the first place. The framework
documents it in `simulation.py` and again in `show_007`, and this fix means a reader who never
finds either of those still has the correct date on the row in front of them. Whether the offset
also deserves a name in the published schema is a larger question about the record's shape, and
not one a one-line fix should answer.

## Validation

```
uv run --no-sync ruff check src/ tests/          # clean
uv run --no-sync pytest -q                       # 691 passed
uv run --no-sync python showcases/show_00N_*/run.py   # all eight OK
```

`show_007` is the sharp one: it rebuilds every mark from the published `vqapr.account` table using
only primitive round-tripped values, and asserts the result is field-for-field equal to what the
run actually committed. It exercises this exact row and passes.

Found from outside the package, in `kwam-enhanced-index/vqapr-testbed-2/`, while building
Fama-French-family factors on 4,841 Korean names.
