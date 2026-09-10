# What `decide()` is handed, and the lookback that decides it

## Contents

- Two read verbs, one per grain
- `current()` versus `latest()`
- The lookback pair — the one that is silently wrong
- Types

## Two read verbs, one per grain

`inputs()` returns a mapping from an alias you name to
`va.DatasetInput(dataset_id=, fields=, lookback=)`. Which verb reads it follows the dataset's
`grain`, and each verb refuses the other grain by name.

**`call.read(alias, field)` on a panel grain** (`instrument_instant`, `instant`) returns a
`PanelWindow`: `instants` (the same for every name) × `instruments`. **`matrix()`** is the window as
one float array — rows are the instants (the last row is the newest), columns are `instruments`,
`NaN` where a name had no value — so a cross-sectional signal is one numpy expression over every
name, and 3,000 names cost what ten do. `values[name]` is one name's values over the instants,
`None` where it had none, for a question about a single name. It is a slice of a panel the run
built once — arithmetic, not a query.

**`call.rows(alias)` on `grain: rows`** returns a tuple of `Observation`s, one per (instant,
instrument), each carrying `instrument_id`, its own `available_at` and `values`. Names interleave
within an instant.

## `current()` versus `latest()`

- **`current()`** — the cross-section at the **last instant**. A name with no row there is
  **absent**, not carried forward.
- **`latest()`** — the newest value per name anywhere in the window, however old.

On a sparse table — where a name has a row only on the sessions it was eligible — a decision
almost always wants `current()`. **`latest()` will trade an ineligible name on a stale value**, and
nothing complains: the value is real, it is just from a date the name should not have been in the
book.

Reach for `latest()` only when staleness is the thing you mean, and say so in a comment.

## The lookback pair — the one that is silently wrong

They are a pair, and the wrong member passes every check.

**`RowsLookback(rows=N)`** gives each name **its own** last N observations. On an unbalanced panel
the batch's calendar span is therefore set by the sparsest name, and is unbounded above: a real
1,637-name universe asking for 313 rows got rows spanning **1,865 sessions, back eight years**.

That is right for a **per-name** question — a trailing return, a moving average.

**`CalendarLookback(days=N, timezone=...)`** gives every name the **same** window.

That is what a **cross-sectional** question needs — a covariance matrix, a factor regression,
anything date-aligned.

**Why the wrong one is dangerous rather than merely wrong:** a correlation matrix built on
`RowsLookback` mixes a live name's recent returns with a delisted name's decade-old ones. Every
number is finite, every check passes, and the matrix is meaningless.

Scaffold with `--lookback N` for the first and `--calendar-lookback DAYS` for the second.

## Types

A value arrives as the type the dataset declared in `field_types`: `DOUBLE` → `float`, `INTEGER` →
`int`, `VARCHAR` → `str`, `TIMESTAMP_TZ` → an aware `datetime`.

Registration compared that declaration against the file once, and a `DECIMAL` column was refused
there — **so `Decimal` never arrives from a dataset.**

Where you want exact arithmetic on a price, cross once:

```python
Decimal(str(value))     # not Decimal(value), which inherits the float's binary expansion
```
