# 045 — A `DataRequirement` can name columns and a window but not which rows, so a long-format dataset delivers 153 rows for every one the model keeps

**Status: CLOSED 2026-09-01** by [`123-a-field-is-an-expression-and-instrument-is-optional.md`](../implementations/123-a-field-is-an-expression-and-instrument-is-optional.md)
(lane C of the read-path campaign). **The diagnosis was upheld and the proposed mechanism was not**,
and both halves of that survive the implementation.

Row selection lives where the dataset is registered, as part of what a field *is*: `fields` values
are expressions, so `net_income` can be
`arg_max(value, dump_last_modified) FILTER (WHERE account_code = '111000')` and the 153 rows this
file measured are never read. `DataRequirement` stayed small: it is now a dataset id, a field id and a
lookback, with no `consumer_id` — the framework stamps that. It briefly had no `dataset_id` either,
until the owner overturned the uniqueness premise that removed it (see `049`).

**This file's line was honoured more strictly rather than less.** The author writes an expression,
never a statement, so there is no `FROM` and no `GROUP BY` to reach and no closed vocabulary to keep
closed as it grows. Registration refuses an expression containing `SELECT`, which is the one
expression form that could read rows the window excludes.

Originally scheduled under the campaign anchored at
[049](049-following-the-packages-own-data-guidance-costs-six-hundred-times.md).

**Upheld:** rows the model discards are read, boxed, validated and carried across the boundary
because nothing can say which rows are wanted. 153:1 stands, and it is a framework gap.

**Rejected: the `where=` argument on `DataRequirement` proposed in "The shape of the fix" below.**
The row selection belongs where the dataset is registered, as part of what a field *is*
(`fields: { net_income: arg_max(value, dump_last_modified) FILTER (WHERE account_code = '111000') }`),
not as an argument the consumer passes. Two reasons, and neither contradicts this file's reasoning:

1. **Which rows constitute `net_income` is a property of the dataset, not of one consumer's
   request.** Every model that wants net income wants the same rows; making each ask separately
   invites them to disagree.
2. **`DataRequirement` must stay a field id and a lookback.** It is the surface an author touches
   most, and every argument added to it is paid by everyone.

**This file's own constraint is honoured more strictly, not less.** Its "line it must not cross" is
that an arbitrary SQL string reaching `observation_rows` is a look-ahead path with a friendly name.
Under the ruling the author writes **an expression, never a statement** — no `FROM`, no `GROUP BY`,
no `available_at` in reach — so the concern is answered by grammar rather than by a vocabulary that
has to be kept closed as it grows. The three properties this file asks for survive: only declared
fields, values never string-composed, and the selection recorded in provenance (better: it is in the
registration, so `show dataset` states it and the run's `source_digest` covers it).

**Status when filed:** open. Found 2026-08-31 by a profiling pass in
`kwam-enhanced-index/vqapr-performance-testbed/`, against `vqapr-0.2.0a2` (built wheel).
**Touches:** `src/vqapr/data/requirements.py` (`DataRequirement`); `src/vqapr/data/scan.py:707`
(`observation_rows`, whose `predicates` list is built from the lookback and the instrument list and
nothing else); `src/vqapr/data/windows.py` (`AccessRecord`).

Sibling to [038](038-one-instrument-list-filters-every-requirement.md), which reports that the one
filter a requirement *does* get is the wrong shape for a second dataset. This reports the filter it
does not get at all.

**Severity is filed separately.** This is one surface of the gap measured in [049](049-following-the-packages-own-data-guidance-costs-six-hundred-times.md): the identical model on a reshaped source is 614x faster with byte-identical output. Ranked alone this reads as a moderate optimisation, which is exactly the mis-triage 049 exists to prevent.


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
after its account-code test as well — 12 codes for 9 items       3,617   (0.65%)
```

**153 rows are read, boxed into a dict, validated, counted, and handed across the boundary for every
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

Rows drop 153x. Wall clock will not fall as far. The Python passes (about half of the measured
window cost — see [044](044-the-read-path-revalidates-eight-column-names-once-per-row.md)) fall with
the row count; the SQL still has to touch the file, and how much duckdb prunes depends on whether
`account_code` and `statement_scope` have usable row-group statistics in the registered parquet. A
defensible estimate is **4-6x on this model**, with the real number knowable only by implementing it
and re-running the same ladder.

**The upper bound was measured rather than estimated.** The same model logic — its later steps
called into rather than re-typed — was run against a source whose account axis is pivoted into
columns and whose scope and settlement tests are pre-applied. Same evaluation instants, same
instruments, same output fields, same workspace, back to back in one process:

```
1,600 instruments x 4 evaluations

              wall     per eval    emitted    where it went
long        806.61s     201.65s      5,098    normalize=428.06s  sql=319.65s  query=43.10s
wide          1.31s       0.33s      5,098    compute=0.36s  normalize=0.30s  sql=0.22s
                                                                             614x

output diff, all eight value fields, both directions:  0 rows only in long, 0 only in wide
source: 84.0 MB -> 0.79 MB     registration: 5.88s -> 0.10s
```

Identical output, checked before the timing was read: a materialization that is 600x faster and
slightly different is a different model rather than a faster one.

**That 614x bundles two changes, and only one of them is what this issue asks for:**

| | rows | cells |
|---|---|---|
| long, as registered today | 553,560 | 4,428,480 |
| **predicate pushed down, still long** | **3,617** | 28,936 |
| pivoted as well | 225 | 3,375 |

A predicate removes the rows the model discards — 153x. The pivot removes the **key columns that
ride beside every value**: a long row carries five identifying columns to deliver one number, so
even 3,617 kept rows carry 28,936 cells to deliver ~3,600 values. That is a further 8.6x a predicate
cannot reach. And the wall gain exceeds both, because the pivoted file is 100x smaller so the scan
itself got cheap.

So the honest reading is: **a predicate is worth several times here, not several hundred**, and the
rest of the 614x is the shape. This issue and a columnar path
([035](035-the-only-data-accessor-is-ninety-times-slower-than-the-file.md)) are complements rather
than alternatives — which is also why the workaround below is so effective, and so tempting.

## The workaround, and why the package should not rely on it

The research side can register `statement-facts` pre-filtered, or pivot it wide in preparation. That
recovers the same speed and gives up the thing the long registration was protecting: which of a
name's many rows on one date the research means is the research's decision, taken in the DataModel
where it is written down and reviewable, not in an ETL step upstream of the framework. The package
tells authors to keep vendor grain. It should then let them read it narrowly.
