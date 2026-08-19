# A frozen horizon is read once

## Why this exists

`docs/code-review/2026-08-19-vqapr-performance.md` items P1-2 and P2-6 are two costs in the same
function, `FillConvention.select_target`, with the same cause: **a fact that cannot change during a
frozen run was recomputed on every callback.**

1. The set of candidate execution instants was re-scanned from the source on every accepted
   intent, materialising every remaining instant in the horizon as a Python tuple, and then
   effectively using the first eligible one.
2. The venue-local calendar was walked day by day to the end of the run, calling
   `_local_target(day)` and **discarding the result**. It was a pure validation loop that proved
   the same days again on every callback.

Both are run-invariant. The execution table is frozen for the run, so its instants are frozen too,
and resolving a venue-local target is a pure function of the day.

## What changed

`ExecutionHorizon` is a new run-lifetime object holding the sorted candidate instants plus a cache
of resolved venue-local targets and a high-water mark of the calendar span already proved.

- `FillConvention.build_horizon(...)` reads the instants once, from the frozen run start to the
  frozen run end.
- `select_target(..., horizon=...)` bisects into that tuple instead of re-scanning, and asks the
  horizon for local targets so each day is resolved at most once per run.
- `validate_calendar` proves only the span not already proved, tracked by `_validated_through`.

`horizon` defaults to `None`, which keeps the original behaviour exactly: scan per call, walk the
calendar per call. Every existing caller and test is unaffected. `SimulationFlow` builds one
horizon lazily on first accepted intent and passes it thereafter.

**Ownership stays where the value semantics allow it.** `FillConvention` is a frozen value object
and cannot hold run state, and `ExecutionInputRegistration` is a declaration — `data/sources.py`
states that declaring does not open a file. So the horizon is owned by `SimulationFlow`, which is
the run-lifetime object, and built lazily so that merely constructing a flow still opens nothing.

`_local_target` became public as `resolve_local_target`, because `ExecutionHorizon` now calls it.

## The bound that makes this correct

`build_horizon` reads from `frozen_run.start`, not from the first decision time. A horizon that
began at the first decision would omit instants an earlier callback is entitled to select. The
lower bound must not be later than the earliest decision the run can make, and the frozen start is
exactly that instant.

`select_target` still applies its own `end_time` to the bisected slice, so a caller asking about a
narrower window than the horizon gets the same answer it always did.

## Trade-offs

- A run holds every candidate instant in memory for its duration. For a 10-year daily horizon that
  is a few thousand datetimes, against a full scan per callback.
- `validate_calendar` proves the calendar span the first callback needs, then extends only when a
  later call needs more. A day that resolves ambiguously still raises, but on the first call that
  covers it rather than on every call.
- `SAME_DAY` conventions gain less: they only ever proved one day per call. The instant cache still
  applies.

## Validation

```
uv run pytest -q                                522 passed
uv run pytest tests/exchange/ tests/flow/ tests/acceptance/ -q   189 passed
uv run python .agent/tmp/g4_check.py            G-4 PASS: 64 fields identical to baseline
uv run python .agent/tmp/perf_run_io.py         candidate_instants 84 -> 4, connects 210 -> 130
```

Measured on `showcases/show_005_enhanced_index`:

| | before this record | after |
|---|---|---|
| `candidate_instants` calls | 84 | **4** |
| duckdb connects | 210 | **130** |
| showcase wall time | 7.73 s | **5.44 s** |

Artifacts stay byte-identical:

```
alpha_allocation.parquet      sha256:1446a91285c0d4d74e43c2a459cfe174833716958f99109709548b4b78b16de9
final NAV                     1168064370.53000000
dealt fills                   62
```
