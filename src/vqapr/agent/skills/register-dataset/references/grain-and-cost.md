# Choosing the grain, and what each one costs

## Contents

- The three grains
- What registration costs
- What reading costs
- Registering the vendor's table twice
- How the grain changes what a model is handed

## The three grains

`grain` says what one row IS. Registration refuses a declaration without it.

| grain | one row is | read with |
|---|---|---|
| `instrument_instant` | one value per (available_at, instrument) — a date × ticker table | `read(alias, field)` |
| `instant` | one value per available_at, no instrument axis — an index level, a rate | `read(alias, field)` |
| `rows` | the vendor's grain (long / EAV), unique on `key_fields`, no panel | `rows(alias)` |

**Register a date × ticker table as `instrument_instant`.** That is the shape a panel is built
from and the shape a cross-sectional model reads safely.

The profiler's key report is the evidence for this choice. If no combination of columns is unique
until you add a third or fourth, the table carries several facts per name and date — that is a
`rows` grain, or it needs another key axis, and which one is a question for the user.

## What registration costs

Registration reads the file once per declared logical key. The cost scales with
**rows × key width**, not with file size, at roughly 50M row-keys per second. A 37.8M-row warehouse
registered on six key fields takes seconds, paid once per workspace.

If any `fields:` entry exposes a numeric column, registration reads the file once more to refuse a
NaN or an infinity — one pass for all such columns at once, however many are declared.

**A non-finite value is refused here or nowhere.** Reads trust what registration accepted, so a NaN
that gets past this point reaches a model and propagates through every number it touches while the
run still reports a result. Prepare a genuinely absent value as `NULL`, which is read as a missing
observation rather than as a number.

## What reading costs

This is the side of the ledger that decides the grain.

- **A panel grain** (`instrument_instant`, `instant`) is read into a panel **once per run** — one
  scan — and every later read is a slice of it, by arithmetic.
- **A `rows` grain** is re-cut on the file per read. The cost scales with the **cells the window
  admits** times the key width: every one is read, boxed into a dict and handed across the
  boundary, even the ones the model discards.

One measured pair of the same data registered both ways differed by **614×**, with byte-identical
output.

## Registering the vendor's table twice

When the vendor's grain must be preserved — several rows per name and date, each a fact of its
own — register it **as well**, as `grain: rows`, and derive the `instrument_instant` table from it
with a DataModel.

The reason is not performance. **Which of a name's many rows on one date a research question means
is a research decision**, and keeping that collapse in a reviewable component rather than in an ETL
step is the point.

## How the grain changes what a model is handed

- **`read(alias, field)` on a panel grain** returns a `PanelWindow`: instants × instruments.
  `current()` is the cross-section at the last instant — a name with no row there is absent, not
  carried forward. `latest()` is the newest value per name anywhere in the window, however old. On
  a sparse table a decision usually wants `current()`; `latest()` will trade an ineligible name on
  a stale value without complaining.
- **`rows(alias)` on `grain: rows`** returns a tuple of `Observation`s, one per (instant,
  instrument), each carrying its own `available_at`. Names interleave within an instant.

Each verb refuses the other grain by name.

## Related

- [discouraged-preparation.md](discouraged-preparation.md) — why the collapse belongs in a
  DataModel rather than in the file
