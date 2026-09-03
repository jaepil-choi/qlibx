# 141 — an `InstantsLookback` counts instants

**Closes:** `docs/issues/053`. **Step:** 1 of `docs/refactoring/2026-09-03-the-deletion-campaign.md`.
**Authority:** design `docs/design/the-panel-the-surface-and-the-run.md` §2.4 and §7-1 (the
lookback types follow the grain; `InstantsLookback` is each name's own last n instants, `grain:
rows` only); record `137`, which moved the per-name count under that name.

## Why this exists

Record `137` gave the per-name count a type whose name says what it counts, and left the SQL that
had counted for `RowsLookback` on a panel grain: `count(<field>) OVER (PARTITION BY instrument
ORDER BY available_at DESC, <key fields> DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)`.
On a panel grain a row is an instant, so nothing noticed. On `grain: rows` -- the one grain the
type is admitted on -- a name carries many rows per instant (the `049` generator: two scopes x
up to thirty codes x two bundles x five period rows), and `InstantsLookback(2)` returned the
newest instant's first two rows. The docstring and the refusal text both said instants. The `049`
harness had to declare `InstantsLookback(2000)` and argue in a docstring that 2,000 rows reach
three fiscal years for every name.

## What changed

- **`data/scan.py::observation_rows`, the row-wise ranking.** Each field's rank is
  `dense_rank() OVER (PARTITION BY <instrument>, (<expression> IS NULL) ORDER BY <available_at>
  DESC)`. Every row of one instant gets the same rank, so `rank <= n` admits whole instants;
  partitioning on nullness keeps a null row from taking a rank away from the instants that carry
  a value, and the existing `<expression> IS NOT NULL` in the keep clause drops those rows. The
  ordering by key fields that the row count needed is gone with it. The grouped branch takes the
  same expression (one row per instant there, so nothing changes for it).
- **Both rows-bound proofs count distinct instants.** `_Counted.args` is now, per field, `CASE
  WHEN <field> IS NOT NULL THEN <available_at> END`, and both places that take the proof --
  `_prove_rows_bound` at cold start and the `_PROOF_PREFIX` window aggregate riding in the read
  -- apply `count(DISTINCT …)` to it. The two must agree (the `_Counted` docstring says why); they
  now agree on instants. Counting rows there while ranking instants would have proved a name
  safe on rows and read it short on instants.
- **Docstrings.** `InstantsLookback` says instants, not rows, and what that means on a vendor
  grain. `data/windows.py`'s field-value note names `InstantsLookback` rather than the retired
  meaning of `RowsLookback`.
- **`experiments/exp_049_the_measurement/exp049_models.py`.** `INSTANTS_LOOKBACK` is `12` --
  three fiscal years at four availability instants a year -- instead of `2000` rows argued in a
  docstring.
- **Tests.** `tests/data/test_lookbacks_follow_grain.py` gains the `053` reproduction: one name,
  four instants, three codes; `InstantsLookback(2)` is two instants and six rows; with the 2nd
  null on every row, `InstantsLookback(3)` is the 1st, 3rd and 4th and nine rows.

## What this does not do

- A `rows` grain still admits no `CalendarLookback`. `053`'s second finding records a real
  need; admitting a calendar window on a long table is a ruling, not a bug fix, and is taken
  when a consumer asks (campaign Step 1 "무엇").
- The `TIMESTAMPTZ` values duckdb returns still arrive as pytz-zoned datetimes per row; that is
  `054`, Step 2.

## Validation

```
uv run ruff check src/                              All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs            1319 passed, 21 deselected  (branch point: 1318 / 21)
PYTHONUTF8=1 uv run pytest tests/showcases -m ""    9 passed  (the Step 0 gate: 1 collector + 8 showcases)
```

The `049` measurement, re-taken on this branch with `INSTANTS_LOOKBACK = 12`
(`experiments/exp_049_the_measurement/bench.py --instruments 1600 --evaluations 4`), the fast
suite running alongside:

| side | wall | per eval | read |
|---|---:|---:|---:|
| `rows` | 147.61s | 36.90s | 144.87s |
| `expr` | 2.69s | 0.67s | 0.99s |
| `wide` | 1.96s | 0.49s | 0.27s |

**Anti-join zero rows both directions on all three pairs**, 6,400 rows published by each side.
The `rows` wall fell from 372.57s (release `0.3.0`, 2,000 rows per name) because twelve instants
read fewer source rows than two thousand rows did; that is the declaration meaning what it says,
not a read-path change. The read is still 98% of the `rows` side, which is `054` (Step 2).
