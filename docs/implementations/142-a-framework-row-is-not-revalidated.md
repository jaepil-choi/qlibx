# 142 — a row the framework built is not validated again

**Closes:** `docs/issues/archive/054`. **Step:** 2 of `docs/refactoring/2026-09-03-the-deletion-campaign.md`.
**Authority:** the `035` ruling (validation happens at registration; the read path is trusted),
already applied to the other read path by record `119` (`docs/issues/archive/044`).

## Why this exists

`054` profiled one evaluation of the `049` harness's `rows` side: 9.85s of `rows(alias)`, of
which 2.92s was the duckdb scan and 6.81s was building `Observation`s -- `_copy_values` checking
every value's key character by character (14.6M `isspace` calls for 159k rows), `_scalar` per
value, `_tz_aware` per row. The keys are the alias's declared `fields`, validated when the
`DatasetInput` was declared; the stamp comes from the scan's own `TIMESTAMPTZ` column. Every check
re-proved per row what the declaration proved once. At the measurement's full size that was
roughly 250s of a 372s materialization.

## What changed

- **`authoring.Observation._framework_row(instrument_id, available_at, values)`.** A classmethod
  that builds the frozen dataclass through `object.__new__` and skips `__post_init__`, wrapping
  the caller's dict in a `MappingProxyType` rather than copying and sorting it. Same type, same
  equality, same immutability as the validated constructor; the docstring says who may use it
  and why. `Observation(...)` by hand still runs every check -- `054`'s "what not to do".
- **`models/calls.py::observations`** builds through it. What stays per row is a dict-key
  presence check for the instrument and availability fields and each declared field (schema
  errors that must not thin the result), an `isinstance(datetime)` check, and one attribute read
  (`tzinfo is None`) so a naive stamp from a caller that is not the scan is still refused. What
  is gone is everything that re-validated the names and the scalars.
- **Tests.** `tests/models/test_calls.py`: a framework-built observation equals the one the
  validated constructor builds from the same fields, and is as frozen.
  `tests/models/test_agent_first_authoring.py`: a hand-built observation with a whitespace key is
  still refused while `_framework_row` is not.

## What was reconsidered and left

**pytz.** duckdb hands back `TIMESTAMPTZ` values as pytz-zoned datetimes and pays `fromutc` per
row: 0.42s of the 2.10s read below, now 20% of it. Measured alternatives on 300k rows:
`fetchall` 1.12s; `to_arrow_table().to_pydict()` 0.84s (values arrive with `zoneinfo` tzinfo,
a different tzinfo type on every `available_at` an author sees); `epoch_us` integers 0.10s (no
datetime at all, so the conversion moves to Python and costs more than it saves). The arrow path
would touch every read, the panel included, for a quarter of a fifth. Not taken; recorded here
so the next person does not re-measure it.

## Validation

```
uv run ruff check src/                              All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs            1321 passed, 21 deselected  (branch point: 1319 / 21)
PYTHONUTF8=1 uv run pytest tests/showcases -m ""    9 passed
```

`cProfile` of the `049` harness at the `054` size (`--instruments 80 --years 5 --evaluations 1
--sides rows`), before and after on this branch:

| | before | after |
|---|---:|---:|
| `rows(alias)` read | 6.68s | 2.10s |
| `calls.observations` | 4.68s | 0.21s |
| `scan.observation_rows` | 1.92s | 1.82s |
| pytz `fromutc` (200,980 calls) | 0.43s | 0.42s |

The full `049` measurement (1,600 instruments, four evaluations), the fast suite running
alongside, anti-join first: **zero rows both directions on all three pairs**; `rows` wall
**75.76s** (read 73.54s) against 147.61s at record `141` and 372.57s at `0.3.0`; `expr` 2.48s;
`wide` 1.84s. The read is now the scan plus pytz; the remaining `rows`/`expr` ratio is the cost
of handing 159k rows to Python at all, which is what a `rows` grain means.
