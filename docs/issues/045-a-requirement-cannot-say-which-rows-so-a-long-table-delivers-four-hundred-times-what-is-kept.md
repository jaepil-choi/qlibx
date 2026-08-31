# 045 — A `DataRequirement` can name columns and a window but not which rows, so a long-format dataset delivers 410 rows for every one the model keeps

**Status when filed:** open. Found 2026-08-31 by a profiling pass in
`kwam-enhanced-index/vqapr-performance-testbed/`, against `vqapr-0.2.0a2` (built wheel).
**Touches:** `src/vqapr/data/requirements.py` (`DataRequirement`); `src/vqapr/data/scan.py:707`
(`observation_rows`, whose `predicates` list is built from the lookback and the instrument list and
nothing else); `src/vqapr/data/windows.py` (`AccessRecord`).

Sibling to [038](038-one-instrument-list-filters-every-requirement.md), which reports that the one
filter a requirement *does* get is the wrong shape for a second dataset. This reports the filter it
does not get at all.

## What a requirement can say

```python
DataRequirement.of(consumer_id, dataset_id, fields=(...), lookback=CalendarLookback(days=1150, ...))
```

Which **columns**, and which **window**. There is no way to say which **rows**. `observation_rows`
composes exactly three predicates: `available_at <= evaluation_time`, the lookback bound, and
`instrument IN (...)`.

That is complete for a dataset whose grain is one row per (date, instrument). It is not complete for
one whose grain is finer — and the package's own guidance produces those. `vqapr-enhanced-index-3`
registers `statement-facts` long, keyed on six fields, because collapsing a vendor's grain is a
research decision and not a preparation step. That is the right call. The consequence is that the
row is the unit the model must filter, and the framework hands filtering to Python.

## The measurement

`annual-fundamentals` reads `statement-facts` with a 1,150-day `CalendarLookback` — long enough to
reach two consecutive annual statements, which is what the model is for. One evaluation, 100
instruments:

```
window rows delivered                                          553,560
after the model's scope + settlement-type test                  36,524   (6.6%)
after its account-code test as well                              1,350   (0.24%)
```

**410 rows are read, boxed into a dict, validated, counted, and handed across the boundary for every
one the model keeps.** The discarding happens in the first three lines of `compute`:

```python
if row["statement_scope"] != accounts.CONSOLIDATED_SCOPE: continue
if row["settlement_type"] != accounts.ANNUAL_SETTLEMENT_TYPE: continue
if code not in CODE_TO_ITEM: continue
```

All three test **declared fields against constants known before the evaluation**. Every one of them
is a `WHERE` clause that never got written.

## What it costs, and that it is not "materialization is slow"

Three DataModels, same machine, same universe, same evaluation count, `vqapr-0.2.0a2`:

| model | reads | lookback | 1,600 instruments x 4 evaluations |
|---|---|---|---|
| `annual-fundamentals` | `statement-facts` (37.8M rows, long) | 1,150 days | **492.6 s** |
| `momentum-signal` | `equity-daily` (8.7M rows, daily) | 430 days | 12.2 s |
| `firm-characteristics` | `equity-daily` + one materialized annual | 10 days | 1.6 s |

A factor of 300 between the first and the third. The models are comparable in arithmetic — the third
is arguably the fiddlier one. What differs is how many rows the declared window admits, and the
first one admits 99.76% it will not use.

The slope confirms rows are the axis: `annual-fundamentals` measures `t ~ instruments^1.49` across
{100, 400, 1600} while `momentum-signal` measures `^0.99` and `firm-characteristics` `^0.47`.

## The shape of the fix, and the line it must not cross

The reason to be careful here is real: the framework owns the point-in-time boundary, and an
arbitrary SQL string handed to `observation_rows` is a look-ahead path with a friendly name. But
**an equality or set test on a declared field is orthogonal to the PIT boundary.**
`account_code IN (...)` says nothing about which instant may be seen.

So the predicate should be a closed, typed vocabulary over declared semantic fields, never a string:

```python
DataRequirement.of(
    MODEL_ID, "statement-facts",
    fields=("account_code", "statement_scope", "settlement_type", "fiscal_yyyymm", "numeric_value"),
    lookback=CalendarLookback(days=1150, timezone=TZ),
    where=(
        Equals("statement_scope", "consolidated"),
        Equals("settlement_type", "D"),
        OneOf("account_code", ACCOUNT_CODES),
    ),
)
```

Three properties worth holding to:

- **Only declared fields.** A predicate on a column the requirement did not declare would be a read
  the declaration does not describe, which is the thing declarations exist to prevent.
- **Values bind as parameters**, exactly as `instruments` already does. No string composition, so no
  injection surface and no way to reach `available_at`.
- **Record it in `AccessRecord`.** This makes provenance *better*, not worse. Today the record says
  which window was read and the narrowing lives invisibly inside `compute`; with the predicate
  declared, the record says which rows the model actually asked for.

## What to expect, stated honestly

Rows drop 410x. Wall clock will not. The Python passes (about half of the measured window cost —
see [044](044-the-read-path-revalidates-eight-column-names-once-per-row.md)) fall with the row
count; the SQL still has to touch the file, and how much duckdb prunes depends on whether
`account_code` and `statement_scope` have usable row-group statistics in the registered parquet. A
defensible estimate is **4-6x on this model** — 493s becoming 80-120s — with the real number
knowable only by implementing it and re-running the same ladder.

## The workaround, and why the package should not rely on it

The research side can register `statement-facts` pre-filtered, or pivot it wide in preparation. That
recovers the same speed and gives up the thing the long registration was protecting: which of a
name's many rows on one date the research means is the research's decision, taken in the DataModel
where it is written down and reviewable, not in an ETL step upstream of the framework. The package
tells authors to keep vendor grain. It should then let them read it narrowly.
