# 054 -- A run-ready horizon has a target

A `next_eligible` run reached its final strategy occurrence with no execution snapshot remaining
inside `end`. Preflight accepted it. The simulation executed 163 earlier occurrences and mutated
account state, then the final callback produced an intent and `_accepted_intent` raised:

```
simulation.callback.intent: no exact execution target exists within the run horizon
```

The failure code was `simulation.callback.intent.ValueError`: the Python exception class, not a
diagnosis. Extending `end` happened to fix it, but nothing before the failed run said that the last
callback's target had to fit inside the horizon.

Reported as F-006 in `kaist-thesis/vqapr-testbed/FRICTION.md`.

## What changed

`preflight_run` now builds the execution horizon once and calls the declared fill convention for
every frozen strategy occurrence. A callback may return `NoDecision`, but preflight cannot assume
that it will. If an accepted intent at an occurrence has no exact target, the declaration is not
run-ready and is refused before any callback mutates state.

The refusal is structured:

- stage: `preflight.execution`
- family: `EXCHANGE`
- code: `preflight.execution.target_outside_horizon`
- mutation: `false`
- observed: selector, run end, and unresolved occurrence count
- examples: bounded occurrence ids and their evaluation times
- retry: extend `end`, correct the execution table, or choose a selector that resolves inside the
  horizon

The horizon is read once. Calling `select_target` without it would scan the physical execution
table once per occurrence and could observe different bytes while preflight is proving one run.

## A fixture that was not run-ready

The existing preflight fixture had strategy callbacks at 09:00 and 10:00, an execution snapshot at
15:30, and `end=10:00`. Every test called that object run-ready, but neither callback could fill
inside its horizon. The new validation correctly rejected five existing tests until the fixture
was repaired: its end is now 15:30, after the execution snapshot. Its monitoring occurrence moved
to 16:00 so the original assertion that monitoring is outside the slice remains true.

The execution fixture now has snapshots at 09:30 and 15:30. The regression case uses callbacks at
10:00 and exactly 15:30 with `next_eligible`: the first resolves at 15:30; the last requires a
strictly later snapshot and is the sole unresolved occurrence. This reproduces the measured edge
rather than constructing a horizon where every callback is impossible.

## Availability guidance

F-005 was a separate confidently wrong timestamp: a pyarrow cast attached a timezone to the
underlying epoch value instead of interpreting a naive wall clock in `Asia/Seoul`. The column was
schema-valid and nine hours wrong, which registration cannot diagnose.

The installed skill and dataset template now require one known-instant round-trip before converting
the full file. They name `pyarrow.compute.assume_timezone` as an explicit localization operation
and warn that a cast is not localization. Tests pin that the emitted template and installed skill
carry both the round-trip and operation name.

## Trade-off

Preflight now reads distinct execution instants from the physical source. The simulation builds its
own horizon again because `FrozenRun` freezes declarations, not physical bytes; carrying a derived
physical horizon inside its identity would change that contract. The extra preflight scan is the
price of refusing before mutation rather than after a long run. It reads only distinct execution
instants, not the full price payload.

Every strategy occurrence is checked, not only the last one. `next_eligible` usually fails at the
last occurrence, but `same_day` can fail on an interior date whose execution snapshot is missing.
Checking only the edge would preserve that mid-run failure.

## Validation

```
uv run --no-sync pytest tests/flow/test_preflight.py -q
# 9 passed

uv run --no-sync pytest tests/flow/ -q
# 94 passed

uv run --no-sync pytest tests/flow/test_preflight.py tests/cli/test_agent_surface.py -q
# 49 passed

uv run --no-sync ruff check src/ tests/
# clean
```

A full-suite claim is intentionally not made in this record: another agent was concurrently
changing `src/vqapr/transforms/`, `public.py`, transform tests, the PRD, and `uv.lock`. Those files
were neither read as implementation inputs nor staged here.
