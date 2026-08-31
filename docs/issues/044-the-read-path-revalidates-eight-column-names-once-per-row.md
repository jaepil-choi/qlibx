# 044 — The read path re-validates the same eight column names once per row, and that check — not the per-cell value check issue 035 names — is the larger half of `normalize_rows`

**Status when filed:** open. Found 2026-08-31 by a profiling pass in
`kwam-enhanced-index/vqapr-performance-testbed/`, against `vqapr-0.2.0a2` (built wheel). Measured
rather than felt: the ladder and the cProfile dumps are in that directory's `results/`.
**Touches:** `src/vqapr/domain/rows.py:38` (`normalize_rows`); `src/vqapr/data/store.py:93`
(`DuckDbObservationStore.query`); `src/vqapr/data/scan.py:804` (`observation_rows`).

**Read [035](035-the-only-data-accessor-is-ninety-times-slower-than-the-file.md) first.** This is not
a second report of that cost. 035 measured `normalize_rows` at 1.635s of a 3.498s accessor and
attributed it to `normalize_scalar` — "per-cell revalidation", 2.9M calls — and its addendum reasons
carefully about what that per-cell check buys and why removing it without relocating the finiteness
check would trade 1.6s for a silent NaN. That reasoning is right about the check it examined.

**It is about the smaller half.** Inside `normalize_rows`, roughly three quarters of the time is not
the value check at all. It is the *key* check, which asks the same question of the same eight
strings once per row.

## The split, measured on one real window

`statement-facts`, 100 instruments, one evaluation, 553,560 rows x 8 columns. Warm session, no
profiler (`microbench.py` in the testbed):

| pass | seconds |
|---|---|
| `scan.observation_rows` — SQL, `fetchall`, one dict per row | 3.072 |
| **`normalize_rows`** | **3.559** |
| the per-row non-null counting in `query` | 0.229 |
| — | |
| `normalize_rows` **with the key check hoisted out of the row loop, nothing else changed** | **0.961** |
| both passes fused, key check hoisted | 0.243 |

Every value still goes through `normalize_scalar` in the 0.961s row. The only difference between
3.559 and 0.961 is *where* the key check happens. **2.60 seconds — 73% of `normalize_rows`, and 38%
of the whole `observations()` call — is spent asking whether `available_at`, `instrument`,
`account_code`, `statement_scope`, `settlement_type`, `fiscal_yyyymm`, `dump_last_modified` and
`numeric_value` contain whitespace.**

## The same thing at function level

cProfile, `annual-fundamentals` materialization, 400 instruments x 2 evaluations, 4,859,555 rows,
373.472s under the profiler:

```
ncalls          tottime   cumtime  function
563,784,036      95.013   140.463  rows.py:48(<genexpr>)      <- any(char.isspace() for char in key)
 38,883,940      59.574   200.043  {built-in method builtins.any}
524,917,250      45.453    45.453  {method 'isspace' of 'str' objects}
          4      32.075   281.119  rows.py:38(normalize_rows)
 38,881,932      17.579    40.186  rows.py:17(normalize_scalar)
```

`any` reaches **200.0s cumulative, 54% of the profile**. `normalize_scalar` reaches 40.2s. The ratio
is five to one, in the direction opposite to the one 035 assumed.

The counts say exactly what is happening: 38,883,940 `any` calls is 4,859,555 rows x 8 columns —
one per cell, but spent on the *name* of the cell rather than its value. 524,917,250 `isspace` calls
is those names walked character by character; the eight names average 13.5 characters.

## Why the fix is unlike 035's

035's item is a genuine trade: the per-cell value check is currently the only thing standing between
a NaN in a registered column and a model consuming it, so removing it requires moving finiteness
validation to registration first. **This one is not a trade.** The rows reaching `normalize_rows`
from `store.query` were built three statements earlier by `observation_rows`:

```python
names = tuple(description[0] for description in cursor.description)
return tuple(dict(zip(names, row, strict=True)) for row in cursor.fetchall())
```

Every row in the batch carries the **identical `names` tuple** — the same `str` objects, from one
cursor description. Checking them per row cannot discover anything the first row did not already
settle. Nothing is given up by checking once.

`ObservationBatch._trusted` already makes exactly this argument one layer up ("rows taken from a
batch this module produced have passed that check once already"). The same argument applies one
layer down and has not been made there.

## What to settle

`normalize_rows` is a general entry point and does take outside input — rows a user's DataModel
emitted, where keys legitimately differ per row. So the per-row check is correct *for that caller*
and wrong for this one. Three shapes, cheapest first:

1. **Memoise the key check.** A module-level `frozenset` of key strings already validated. Hit rate
   is 100% on the read path because the strings are identical objects, and outside input still pays
   full price the first time it presents a new name. Smallest possible diff.
2. **A keyed entry point.** `normalize_rows(rows, keys=names)` — validate `keys` once, then trust
   them for the batch. `store.query` and `observation_rows` are the two callers that can supply it.
3. **Fuse it with the counting pass.** The 0.243s row above. This subsumes the third traversal in
   `query` as well, and is the shape to reach for if 035's ruling ("validation never happens on the
   read path") is implemented — because after that ruling the value check is gone and what remains
   *is* this check plus the counting loop.

Shape 1 is a few lines and is independent of the 035 ruling. Shape 3 depends on it.

## Why it matters beyond one model

`annual-fundamentals` in `kwam-enhanced-index/vqapr-enhanced-index-3/` costs 1,193s for 8
evaluations over 2,795 instruments, and the ladder here reproduces it: 493s for 1,600 instruments x
4 evaluations, of which the boundary probes attribute 48.6% to `normalize_rows`, 44.7% to the SQL,
and **1.9% to the model's own `compute`**. A cost that is 38% of every window read is 38% of every
materialization and of every strategy callback that reads a wide window.
