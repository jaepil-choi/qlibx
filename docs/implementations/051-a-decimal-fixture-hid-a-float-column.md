# 051 — A decimal fixture hid a float column from 691 tests

0.1.0a16 fixed the `vqapr new` templates: both collected `row[field]` raw and then subtracted it
against `Decimal`, so a parquet whose price column is float64 raised

```
simulation.callback.intent: unsupported operand type(s) for -: 'float' and 'decimal.Decimal'
```

mid-run, where `failures[0].code` reads `simulation.callback.intent.TypeError` — a Python class
name promoted to a field, not a diagnosis. That release shipped `Decimal(str(value))` in
`extension/scaffold.py` with **no test and no record**. This closes both, and fixes the second
copy of the same bug that release missed.

Reported as F-004 in `kaist-thesis/vqapr-testbed/FRICTION.md`, severity `blocked`, against the
strategy scaffold used unmodified except for its own marked "one line to change."

## Why the suite did not catch it

`normalize_scalar` passes `float` through as `float` — the store hands a callback whatever the
column holds, by design. So the templates were wrong for any float column, and every test passed.

The reason is one line, and it is in the fixtures rather than the code. Every price fixture in
this suite writes its values as bare DuckDB literals:

```sql
(DATE '2024-03-05', TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', 100.0, 10.0)
```

and `typeof(100.0)` in DuckDB is **`DECIMAL(4,1)`**, not `DOUBLE`. Every model this suite has ever
exercised was therefore handed `Decimal` — the single dtype under which the defect is invisible.
The sample panel is the same story by a different route: `agent/sample/build.py` declares
`PRICE_TYPE = pa.decimal128(18, 4)` explicitly.

A parquet written by pandas, polars, or pyarrow from a float column gives `float`, and that is the
overwhelmingly common case for a price. So the templates were correct for the fixtures and broken
for approximately every real dataset — and no amount of adding tests over the existing fixtures
would have found it.

## What changed

**`agent/sample/reversal_5d.py`** — a16 fixed the two templates in `extension/scaffold.py` and
missed this third copy, which has the identical `values[-1] / values[0] - Decimal(1)` shape three
lines below an identical raw append. It matters more than its line count: `agent/sample/README.md`
presents it as the journey a fresh user materializes to check their mental model, so it is read
and copied. Against the shipped decimal128 panel it works; against the reader's own file it
reproduces F-004 exactly.

**`tests/extension/test_scaffold_runs_on_real_dtypes.py`** — new. Its `float_price_parquet`
fixture is the first in this repository whose price column is genuinely `DOUBLE`, via an explicit
`CAST(close AS DOUBLE)`. Five tests:

- both templates are rendered, registered, loaded, and **called** against that fixture — the
  existing `test_the_scaffold_registers_as_written` only proves the door accepts them, which a
  template that raises on its first row satisfies completely;
- `test_the_price_fixture_really_holds_python_floats` asserts `type(row["close"]) is float`. This
  guards the guard: if the fixture ever drifts back to a bare literal, the other tests keep
  passing while testing nothing, which is precisely how the bug shipped;
- `test_neither_template_collects_a_raw_cell` pins `.append(Decimal(str(value)))` in the emitted
  source, so a regression fails on the line that caused it rather than on arithmetic several
  frames away.

`Decimal(str(value))` rather than `Decimal(value)` throughout: via `str` the value keeps the
decimal spelling the column shows, so 105/100 - 1 is exactly `0.05`. Through `Decimal(float)` it
inherits the binary expansion and compares unequal to anything a reader would write down. The
tests assert the exact values, so this is pinned rather than incidental.

## Trade-off

The templates now convert on every row, which costs a `str` and a `Decimal` parse per cell against
an already-Decimal column — measurable only in the fixtures. A column that is already `Decimal`
round-trips through `str` unchanged, so correctness does not depend on which dtype arrives.

Not attempted here: coercing numeric fields to `Decimal` in the DataRequirement/window layer,
which owns the schema and could do this once for every component rather than once per template.
F-004's own "Fix" note raises it as the alternative. It is the larger and better answer, and it
changes the type every existing callback receives — a decision about the data contract, not a
scaffold repair, and not one to make while closing an unrecorded release.

The other fixtures are left decimal. Converting them would be a wide diff over assertions that are
correct as written; what was missing was *a* float fixture, not the absence of decimal ones.

## Validation

```
uv run --no-sync ruff check src/ tests/          # clean
uv run --no-sync pytest -q                       # 696 passed (691 + 5)
uv run --no-sync pytest tests/agent/ -q          # 7 passed, covers the edited sample
```

The regression tests were verified to actually fail. With `.append(Decimal(str(value)))` reverted
to `.append(value)` in both templates, `pytest tests/extension/test_scaffold_runs_on_real_dtypes.py`
reports **4 failed, 1 passed**, the two execution tests raising the exact `TypeError` from F-004
at the emitted file's own line. Restored, 5 passed.

That check found a first draft of these tests that was worthless: built over the existing
`model_price_parquet`, it passed against the reverted templates because that fixture is decimal.
The `CAST(... AS DOUBLE)` is the entire test.
