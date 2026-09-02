# 054 -- a `rows` read spends seventy percent of its time validating names it validated at registration

**Status:** open. Found 2026-09-03 by profiling the `rows` side of the `049` measurement
(`experiments/exp_049_the_measurement/`), on `develop @ 724bdadc`.

**Touches:** `authoring.py::Observation.__post_init__` and `_copy_values` / `_scalar` /
`_tz_aware`; `models/calls.py::observations` (where the `Observation`s are built);
`models/contexts.py::rows`.

## What was measured

One evaluation of the `OnRows` model, 80 instruments, five fiscal years, 158,744 observations
returned. `cProfile`, cumulative:

```
rows(alias) total                                     9.85 s
  scan.observation_rows  (duckdb, ranked SQL)         2.92 s   30%
  calls.observations     (building Observation)       6.81 s   70%
    Observation.__post_init__                         6.48 s
      _copy_values                                    5.61 s
        any(c.isspace() for c in name)  14.6M calls   2.79 s     <- per value, per row
        _scalar                          952k calls   0.65 s
      pytz timezone / fromutc            952k calls   0.86 s
      _tz_aware                          317k calls   0.43 s
```

At the measurement's full size (1,600 instruments, four evaluations) the read side was 365.67 s of
a 372.57 s materialization; the same 70/30 split puts roughly 250 s of it in Python validation of
rows duckdb had already returned.

## What is being validated, and where it was already true

`_copy_values` checks, for every value of every row, that the field name is a non-empty string
with no whitespace and is not a reserved name. The names are the registration's `fields` keys --
validated by `DatasetRegistration.of` at registration and again by `check_schema`, and the read
selects exactly those names. The `available_at` is a tz-aware timestamp the scan's own
`TIMESTAMPTZ` column guarantees. So the per-row checks re-prove per row what the declaration
proved once, which is the shape `docs/issues/044` closed on the other read path (*"the read path
revalidates eight column names once per row"*, record `119`).

The `pytz` share is separate: duckdb hands back tz-aware datetimes carrying `pytz` zones and each
row goes through `fromutc`; the package itself keeps `pytz` only because duckdb requires it at
import (record `129`).

## What to do

Validate the names once per read -- they are one tuple, the alias's declared fields -- and build
the `Observation`s with a constructor that skips `__post_init__` for rows the framework itself
produced; keep `__post_init__` for an author constructing one by hand. The `035` ruling applies as
written: validation happens at registration, and the read path is trusted.

## What not to do

Do not drop the checks from `Observation` itself. An author can construct one, and a value
dictionary with a whitespace key would otherwise reach a materialization output unnoticed. The
distinction is who built the row, not whether rows are checked.
