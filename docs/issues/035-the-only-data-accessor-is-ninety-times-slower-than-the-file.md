# 035 — The only data accessor a model author has is ~90x slower than reading the same file, and it is the entire cost of a rolling-window run

**Status:** **owner-decided 2026-08-31, not yet implemented.** The ruling: **validation never
happens on the read path.** Registration is where data is validated, and what a registration accepts
is thereafter trusted. What a registration cannot honestly check - a value that only turns out to be
wrong at runtime - is not chased; it blows up, loudly, where it happens.

That settles the addendum below: the 1.6s per evaluation spent revalidating rows the package itself
just read is **removed**, with only the checks a registration can honestly make moving there. The
columnar accessor and the rolling-window scan reuse remain open design questions.

**Status when filed:** open. Found 2026-08-30 by the first-time-user journey in
`kaist-thesis/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-011**,
`slowed` / `code`. Profiling was requested by the user, so this is measured rather than felt.
**Touches:** `ObservationBatch.rows` (`src/vqapr/data/windows.py`); `ScanSession` and
`DuckDbObservationStore` in `vqapr.public`; `MaterializationSpec`.

## One evaluation, broken down

PCA K=5, 1,637-instrument roster, one instant, 477,628 rows:

| stage | seconds | share |
|---|---|---|
| **`load` — `context.window.observations(req).rows`** | **3.8366** | **88.5%** |
| `scan` — the author's loop over the returned dicts | 0.2277 | 5.3% |
| `pca` — 690x690 correlation + `eigh` | 0.2178 | 5.0% |
| `pivot` — numpy scatter into (session x instrument) | 0.0519 | 1.2% |
| `filter` / `regress` / `residual` / `emit` | 0.0031 | 0.1% |
| **total** | **4.3372** | |

The estimator the paper describes — a 252x690 correlation matrix, a full eigendecomposition, and 690
sixty-day regressions — is **5.1% of wall clock**. Everything else is getting the data to it.

## The comparison that makes it a finding rather than a shrug

The identical 477,628 rows, same parquet, same predicate, same four columns:

```
duckdb -> arrow      477628 rows   0.042 s     (0.187 s cold, then 0.042 s warm)
duckdb -> to_pylist  477628 dicts  1.909 s
vqapr  -> .rows      477628 dicts  3.837 s
```

**Two costs, and they should be addressed separately:**

1. **~1.9s is the `list[dict]` contract itself.** `ObservationBatch` has exactly two public
   attributes, `rows` and `access`, and `rows` is a Python list of `dict`. Any consumer that wants a
   matrix pays to build 477,628 dicts and then pays again to tear them apart — the `scan` stage
   above exists solely to undo the boxing. Handing back an Arrow table or column arrays makes both
   stages disappear. For a per-name reduction (the scaffold's example) dicts are fine; for a
   cross-sectional model they are the dominant cost of the run.
2. **~1.9s is overhead above that**, unattributed. duckdb reaches `to_pylist` in 1.95s total; vqapr
   takes 3.84s to reach the same place from the same file.

## Fixed cost per evaluation, measured

Shrinking the roster from 1,637 to 873 names dropped the batch from 477,628 to 271,070 rows and
`load` from 3.84s to 2.57s — returning **byte-identical output, 690 residuals either way**. Fitting
the two points: roughly 5.4us/row plus **~0.9s fixed per evaluation**. Over 2,096 daily evaluations
that fixed component alone is ~31 minutes in which no data moves.

## The structural waste

Consecutive daily evaluations share 322 of their 323 sessions. Each one re-reads the entire window
from scratch. Nothing in the public surface exposes a warm scan, a cached window, or an incremental
cursor — `ScanSession` and `DuckDbObservationStore` are both exported from `vqapr.public`, but
`SKILL.md` names neither and `MaterializationSpec` gives no way to hand one in. **A rolling window
is the normal shape of this entire literature, and the framework recomputes each window
independently.**

## What it cost this run

2,096 evaluations x 4.34s = **2h 32m per (factor model, K)** at full roster, or **1h 45m** with
period-segmented rosters. Times two residual models = 3.5 hours before a single simulation ran. The
final three runs plus one materialization spent about 21 minutes of compute, of which roughly 19
were loading; every workload profiled spent 84-95% of its time inside the accessor.

## The workaround, and why it is not a fix

Segmenting the roster by period. It is only safe because the reporter verified output equality by
hand, and that verification is theirs to redo every time the roster or window changes. Nothing in
the package suggested it, and nothing warned that `.rows` is the expensive part.

## The ~1.9s of "unattributed overhead" is attributed, 2026-08-31

Reproduced on `develop` against a synthetic parquet of the same shape (480,000 rows, 1,600 names,
300 sessions, four declared fields), one evaluation, warm session:

| stage | seconds |
|---|---|
| `scan.observation_rows` -- SQL plus building the dicts | 1.656 |
| **`normalize_rows` -- per-cell revalidation of what was just read** | **1.635** |
| the per-row non-null counting in `DuckDbObservationStore.query` | 0.208 |
| **`observations()` total** | **3.498** |

So the second cost this file splits out is not unattributed and not mysterious: it is
`normalize_scalar` called once per cell -- 2.9M calls here -- on rows the package itself just read
from its own registered parquet. It is the single largest addressable item, and it is 47% of the
accessor.

**What it is actually buying** decides whether it can go. `normalize_scalar` refuses a non-finite
float, a naive datetime and a non-portable type. Dataset registration does **not** check value-column
finiteness today -- `scan.positive_finite_when_true` exists but is on the execution-input path -- so
this read-time pass is currently the only thing standing between a NaN in a registered column and a
model consuming it. Removing it without moving the check would trade 1.6s per evaluation for a
silent NaN, which is the class of failure this package exists to refuse.

That makes the cheap version of item 2 a **relocation** rather than a deletion: check finiteness once
per column at registration, where it costs one scan of a file that is about to be read thousands of
times, and let reads trust the declaration they already validated.

## What to settle

Whether `ObservationBatch` grows a columnar accessor beside `.rows` (Arrow table, or per-field
arrays), and whether a rolling-window materialization can reuse a scan across consecutive
evaluations. The first is a contract addition with a clear beneficiary; the second is the larger
question and is the one worth a design note.
