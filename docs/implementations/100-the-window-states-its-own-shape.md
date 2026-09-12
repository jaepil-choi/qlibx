# 100 — The observation window states its own shape, on the surface an author reads

**Closes:** `docs/issues/archive/031-the-type-a-datamodel-must-consume-is-not-importable.md`.
**Branch:** `fix/031-observation-batch-is-public`.

## Why this change exists

`ModelWindow.observations(requirement)` is the only method a DataModel author can call to see any
data at all, and its signature names its return type. That type was:

| probe | before |
|---|---|
| `hasattr(vqapr.public, "ObservationBatch")` | `False` |
| docstring on `ObservationBatch` | none |
| docstring on `ModelWindow.observations` | none |
| `ObservationBatch` or `.rows` in `SKILL.md` | absent |

So three questions that decide everything an author writes next had no answer on the public
surface: does a row carry its own `available_at`, are rows ordered by time, and are they grouped by
instrument or interleaved. The reporting journey answered them by registering a throwaway DataModel
whose `compute` printed `sorted(rows[0].keys())` — a full register → materialize → show cycle spent
on one type's field names — and then recorded the part that matters: **the ordering was confirmed
on one window of three names at one instant, and every residual in the run then depended on it.**
Nothing in the package promised it.

The shipped scaffold makes the same unstated bet: `values[-1] / values[0] - 1` is a trailing return
only if rows are time-ordered, which was said by arithmetic in emitted code and by nothing else.

## What changed

- **`ObservationBatch` is exported from `vqapr.public`** and has a docstring naming its row keys,
  its ordering guarantee, and what `access` is for.
- **`ModelWindow` joins it in `__all__`.** It was importable and undeclared, while the shipped
  constraint scaffold has always emitted `from vqapr.public import ... ModelWindow` — the facade's
  own list disagreed with the code the package writes for its users.
- **`ModelWindow.observations` gained a docstring** pointing at the batch for shape and at
  `snapshot` for the newest cross-section.
- **`SKILL.md`'s DataModel section states the shape** — flat tuple of dicts, per-row `available_at`
  and `instrument`, aliases rather than physical column names, interleaved instruments, and how to
  take a cross-section.

## What the docstring says, and how it is now true rather than observed

**Ordering is `available_at` ascending, then the dataset's registered key fields.** This is not a
description of what one query returned: `scan.observation_rows` builds `ORDER BY` from
`(available_at, *key_fields)` and pushes it into SQL for both lookback shapes.
`tests/data/test_observation_batch_shape.py` pins it for both, so a change that drops the clause
fails there rather than in someone's factor.

**A value keeps its parquet column's type, and the reporter's note is corrected.** They recorded
*"values arrive as float, not Decimal"*, true of their source. Measured here: a `DOUBLE` column
returns `float` and a `DECIMAL` column returns `Decimal`, in the same row — duckdb hands back what
the column holds and `normalize_scalar` passes both through. That is why the scaffolds write
`Decimal(str(value))` and never `Decimal(value)`, and it is the same fact
`tests/extension/test_scaffold_runs_on_real_dtypes.py` was written about from the other direction.
The docstring states the rule rather than either observation.

## Validation

| check | result |
|---|---|
| `tests/data/test_observation_batch_shape.py` (new) | 6 passed |
| `tests/boundaries/test_public.py` (the pinned `__all__`) | 11 passed |
| fast suite | **1435 passed**, 14 deselected |
| `-m slow` | **14 of 14 passed** |

The new file proves the three questions rather than restating them: ascending stamps under both
`RowsLookback` and `CalendarLookback`; the exact key set of a row; both column types in one row; and
that the batch is **not** sorted by instrument — an assertion that fails if the rows ever start
arriving grouped, which is the reading a per-instrument reduction silently assumes.
