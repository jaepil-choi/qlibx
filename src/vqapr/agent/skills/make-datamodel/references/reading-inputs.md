# What `compute()` is handed, and the lookback that decides it

## One evaluation time per output row

A StrategyModel has one evaluation time per decision. A DataModel produces a table, so it has
**one evaluation time per output row** — each session computes the rows that are valid as of that
session, and only from what was available then.

That is the whole look-ahead guard. There is no separate detector, because there is no path by
which a calculation over the entire period reaches a single session.

## Two read verbs, one per grain

`inputs()` maps an alias to `vq.DatasetInput(dataset_id=, fields=, lookback=)`. Which verb reads it
follows the dataset's `grain`, and each refuses the other by name.

**`read(alias, field)` on a panel grain** (`instrument_instant`, `instant`) returns a
`PanelWindow`: `instants` × `instruments`. **`matrix()`** is the window as one float array — rows
are the instants (the last row is the newest), columns are `instruments`, `NaN` where a name had
no observation — so a cross-sectional computation is one numpy expression over every name.
`values[name]` is one name's values, `None` where absent, for a per-name question. It is a slice
of a panel the run built once — arithmetic, not a query.

**`rows(alias)` on `grain: rows`** returns a tuple of `Observation`s, one per (instant,
instrument), each with its own `available_at`. Names interleave within an instant.

## `current()` versus `latest()`

- **`current()`** — the cross-section at the last instant. A name with no row there is **absent**,
  not carried forward.
- **`latest()`** — the newest value per name anywhere in the window, however old.

On a sparse table `latest()` will hand you a stale value without complaining. Reach for it only
when staleness is what you mean.

## The lookback pair

They are a pair, and for a DataModel the wrong member is usually the dangerous one.

**`RowsLookback(rows=N)`** — each name gets **its own** last N observations. On an unbalanced panel
the batch's calendar span is set by the sparsest name and is unbounded above: a real 1,637-name
universe asking for 313 rows got rows spanning **1,865 sessions, back eight years**.

Right for a **per-name** question: a trailing return, a moving average.

**`CalendarLookback(days=N, timezone=...)`** — every name gets the **same** window.

Right for a **cross-sectional** question: a covariance matrix, a factor regression, a beta, a
rank — which is most of what a DataModel exists to compute.

**Why the wrong one is dangerous rather than merely wrong.** A correlation matrix built on
`RowsLookback` mixes a live name's recent returns with a delisted name's decade-old ones. Every
number is finite. Every check passes. The matrix is meaningless, and nothing in the result says so.

Scaffold with `--lookback N` or `--calendar-lookback DAYS`.

## Reading is cheap; re-reading is not

A panel grain is read into a panel **once per run** and every later read is a slice of it. A `rows`
grain is re-cut on the file per read, and its cost scales with the cells the window admits times
the key width — every one read, boxed and handed across the boundary even when discarded.

That is why a derived `instrument_instant` table computed once by a DataModel beats reading a
vendor's long table repeatedly: one measured pair differed by **614×** with byte-identical output.

**What memory scales with.** A run holds, per numeric field it reads, one float64 matrix of
(the run's period + its longest lookback on that dataset) × its declared instruments — not the
source's whole history, and not a copy per name. Halving the period halves it; the lookback and
the instrument count are the other two knobs. Under `vqapr run ... --jobs N` the batch bakes each
dataset once and every worker maps the same bytes, so a run over the whole universe costs the
machine that matrix once, not once per worker. Size a sweep's `--jobs` by memory per worker (the
interpreter's floor is about 130 MB), not by cores.

## Types in

A value arrives as the type the dataset declared in `field_types`: `DOUBLE` → `float`, `INTEGER` →
`int`, `VARCHAR` → `str`, `TIMESTAMP_TZ` → an aware `datetime`. A `DECIMAL` column was refused at
registration, so **`Decimal` never arrives from a dataset**.

For types **out**, see [output-schema.md](output-schema.md) — the rules are different and stricter.
