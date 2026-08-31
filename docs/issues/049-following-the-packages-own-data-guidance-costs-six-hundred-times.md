# 049 — A model that follows the package's own data guidance runs 614x slower than the identical model on a reshaped source, and the package offers nothing that closes the gap

**Status when filed:** open, and filed as the **severity** of what
[044](044-the-read-path-revalidates-eight-column-names-once-per-row.md),
[045](045-a-requirement-cannot-say-which-rows-so-a-long-table-delivers-a-hundred-and-fifty-times-what-is-kept.md)
and [035](035-the-only-data-accessor-is-ninety-times-slower-than-the-file.md) each describe one
surface of. Measured 2026-08-31/09-01 in `kwam-enhanced-index/vqapr-performance-testbed/` against
`vqapr-0.2.0a2` (built wheel).
**Touches:** the read path as a whole — `data/requirements.py`, `data/scan.py`, `data/store.py`,
`domain/rows.py`, `data/windows.py` — and, more than any single module, **`SKILL.md`'s data
guidance**, which is what a user follows into this.

## The claim

Registering a dataset at the vendor's grain is what the package tells an author to do, and it is
good advice: which of a name's many rows on one date a research question means is a research
decision, and collapsing it upstream hides that decision in an ETL step nobody reviews.

**An author who takes that advice pays 614x.** Not 614x on a microbenchmark — 614x on a real
materialization, publishing byte-identical output, with the model's own arithmetic unchanged.

## The measurement

`annual-fundamentals` reduces a Korean statement warehouse to the annual quantities a Fama-French
sort needs. It was run twice: once against `statement-facts` registered long at the vendor's grain,
and once against the same facts with the account axis pivoted into columns and the scope/settlement
tests pre-applied. Same evaluation instants, same instruments, same output fields, same workspace,
**back to back in one process**:

```
1,600 instruments x 4 evaluations

              wall     per eval    emitted    where the time went
long        806.61s     201.65s      5,098    normalize=428.06s  sql=319.65s  query=43.10s
wide          1.31s       0.33s      5,098    compute=0.36s  normalize=0.30s  sql=0.22s
                                                                             614x

source parquet      84.0 MB  ->  0.79 MB
registration         5.88 s  ->  0.10 s
```

**The output is identical.** All eight published value fields, both directions, full anti-join:
zero rows only in long, zero only in wide. That was checked before the timing was read, because a
materialization that is 600x faster and slightly different is a different model rather than a
faster one. The wide model does not reimplement the reduction — it calls the long model's own
`_derive`, its account-code fallback ordering and its prior-year asset guard.

**The pivot is an exact reduction, and that was checked rather than assumed.** It holds only if no
`(instrument, fiscal_period, account_code)` and no `(instrument, fiscal_period)` appears at more
than one `available_at`. Both are zero on this warehouse, and the experiment re-checks them on
every run and refuses to proceed otherwise. That is a property of the data, not of the code.

## What the model's own time is

1.9%. At the widest ladder point the boundary probes attribute 48.6% of a long materialization to
`normalize_rows`, 44.7% to the SQL, 4.7% to the store's own bookkeeping, and **1.9% to
`DataModel.compute`** — the part the author wrote and the only part that is about finance.

## Why it is 614x and not 153x — the two halves

|  | rows | cells |
|---|---|---|
| long, as the package's guidance produces it | 553,560 | 4,428,480 |
| a predicate pushed down, still long (issue 045) | 3,617 | 28,936 |
| pivoted as well | 225 | 3,375 |

* **A predicate removes rows the model discards** — 153x here.
* **The shape removes the key columns that ride beside every value.** A long row carries five
  identifying columns to deliver one number, so even the 3,617 rows a predicate would keep still
  carry 28,936 cells to deliver ~3,600 values. A further 8.6x that no predicate can reach.
* **And the file itself became 100x smaller**, so the scan got cheap too — which is why the wall
  gain exceeds both cell counts.

This is the reason to file it as one issue rather than leave it as three. 045 alone is worth
"several times". 044 alone is worth ~40% of a window read. 035's columnar accessor addresses the
boxing. **None of them alone is 614x, and a reader triaging them separately would rank each as a
moderate optimisation.** Together they are the difference between a 20-minute rebuild and a
two-hour one for this research environment, and between `annual-fundamentals` costing 1,193s and
costing about 5.

## The part that makes it a package problem rather than a user problem

The remedy exists and the user can reach it — pivot in preparation, register the wide form. It
works, it is 0.3 seconds to build, and this issue's own measurement is that remedy.

**But taking it means overriding the package's data guidance.** Concretely, the pivot had to decide
three things the long registration deliberately left open:

1. consolidated vs separate statements — fixed to consolidated;
2. annual vs quarterly settlement — fixed to annual;
3. which download bundle wins when two rows disagree — fixed to latest `dump_last_modified`.

The third is not optional: a column cannot hold two values, so any pivot must resolve it. So the
author's choice is between **a defensible data model that is 600x slow** and **a fast one that has
moved research decisions into an ETL step**. The package currently makes that a real trade, and it
does not have to be one — every one of 044, 045 and 035 removes part of it without asking the user
to give anything up.

What the package does *not* offer, and what would close this:

* no way to declare which rows a requirement wants (045);
* no way to receive a window in columns rather than as one dict per row (035);
* no read path that trusts what registration already validated (044, and 035's owner ruling);
* and no guidance anywhere that says a long registration is expensive to read, so the cost is
  discovered after the schema is committed to, not while it is being chosen.

The last one is the cheapest thing on this list and is worth doing even if none of the others are:
**say in `SKILL.md` that the read cost of a dataset scales with the cells its window admits, and
that a long/EAV registration multiplies those cells by its key width.** An author told that once
will register a second, narrow dataset beside the faithful one on purpose — which is the shape this
research environment arrived at after paying for it.

## Reproducing

`kwam-enhanced-index/vqapr-performance-testbed/`:

```
uv run python wide_experiment.py --instruments 1600 --evaluations 4
```

It builds the pivot, verifies the grain properties, materializes both, diffs the published parquet,
and prints the table above. `pivot_experiment.py` isolates the read alone (10.19s -> 0.048s on one
window), and `bench.py --stage datamodel` is the ladder the 1.9%/48.6%/44.7% split comes from.

**One caution on absolute seconds.** The same long point measured 492.58s in an earlier ladder and
806.61s here, at `busy` 1.0 in both — no other process was taking the core, so the likeliest cause
is clock behaviour under a long single-threaded load. **The 614x is a within-process ratio measured
back to back and does not depend on that**, but absolute seconds from different sessions should not
be compared.
