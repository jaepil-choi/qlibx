# Structured error contract for the point-in-time decision surface

## Why this change exists

The previous pass gave `research`, `execution` and `artifacts` a structured error contract
but stopped there. `strategy` kept raising bare `ValueError`, which left the contract half
kept: an agent could not tell where a stable code was available and where it would get a
traceback, so it had to pattern-match message strings everywhere to be safe. A contract
honored in half the package is worse than either extreme.

`strategy` was the wrong half to leave out. It owns the two failures the product exists to
prevent — no-look-ahead (PRD §2.5, §6.4) and the child-context boundary (PRD §7.3) — and
those are hit far more often than a reconciliation mismatch in `execution`.

## What outcome it serves

An agent that trips the no-look-ahead boundary now receives a code it can look up, the
boundary that decided the refusal, and the specific observations that crossed it:

```json
{"code": "QLIBX_BOUNDARY_LOOK_AHEAD",
 "context": {"dataset": "returns", "decision_time": "2025-02-01T00:00:00",
             "boundary": "available_at", "violation_count": 1,
             "violations": [{"row": "2025-03-01T00:00:00", "column": "A",
                             "available_at": "2025-02-02T00:00:00"}]}}
```

Previously it received `ValueError: dataset returns contains observations available after
decision time` — no code, no `qlibx errors` entry, and not one offending timestamp.

## Behavior change

The 21 `ValueError`/`RuntimeError` raises in `strategy` are now `QlibxError` under a new
`QLIBX_DECISION_*` namespace, 18 codes in total, each with installed recovery guidance.

The namespace is new rather than an extension of `QLIBX_STRATEGY_*`, which
`strategy_manifest` already owns for the declarative manifest/binding path. The two modules
answer different questions — one validates a manifest against registered fields, the other
enforces point-in-time boundaries at decision time — and `QLIBX_DECISION_*` matches the
vocabulary `strategy` already uses (`DecisionContext`, `DecisionResult`, `run_decision`).
It also separates the namespaces ahead of the module rename that review §16 records.

Two contexts carry more than a restatement of the message:

- Look-ahead and child-boundary violations report `violation_count` plus up to five named
  offenders. Counting a violation without naming it forces the caller to re-derive which
  row broke the boundary, which is where guessing starts.
- `CHILD_OBSERVATIONS_CHANGED` and `CHILD_AVAILABILITY_CHANGED` carry `context.mismatch`,
  the pandas comparison's own report. `_frames_equal_with_nan` computed exactly which cell
  or dtype differed and then discarded it to return a bool; `_frame_mismatch` returns it.

`NestedResearchResult.diagnostics` gains `error_code`. A rejected what-if was already an
answer rather than a crash, but its reason was a string; it is now a code the caller can
branch on.

`evaluate_child` catches `QlibxError` alongside `TypeError`/`ValueError`. This is the one
place the conversion could have silently broken behavior: `QlibxError` extends
`RuntimeError`, so every converted raise inside the child evaluation would have escaped the
rejection path and propagated as a crash. Verified by reverting the widened catch — the
nested-research test fails with an uncaught `QLIBX_BOUNDARY_CHILD_OBSERVATIONS`.

## Trade-offs

- Callers catching `ValueError` from `strategy` no longer catch these failures. The only
  in-package catcher was `evaluate_child`, and the three affected test assertions now
  assert on codes and violation contexts instead of message substrings. This is the same
  break the earlier pass took for `research`/`execution`/`artifacts`; taking it here is
  what makes the contract uniform rather than a third convention.
- Row and column escapes share `QLIBX_BOUNDARY_CHILD_AXIS` and separate on
  `context.axis`, matching how `QLIBX_INVALID_AVAILABILITY_AXES` already reports.
  The first attempt used two codes built by a helper taking the code as a parameter; the
  documentation guard's AST scan cannot see a code that is never a literal at a raise site,
  and correctly reported both as documented-but-unreachable. Keeping the raise sites
  literal keeps that guard honest.
- `_availability_frame` now takes the dataset id so its axis errors can name the dataset.
  Three call sites pass it; the alternative was an error that says an axis is wrong without
  saying whose.
- `optimization` (22 sites) was deliberately left alone. Those validate arguments to pure
  computational functions where `ValueError` is the idiomatic and correct answer; converting
  them would dilute the contract rather than strengthen it.

## Validation

- `uv run ruff check .` and `uv run ruff format --check .` — clean.
- `uv run pytest` — 128 passed, 1 failed.
  - The failure is `tests/acceptance/test_p0_p1_agent_journey.py`, a pre-existing Windows
    `cp949` console-codec error when decoding the CLI subprocess output. Confirmed present
    on the unmodified baseline by stashing this change and rerunning; it is unrelated.
- New assertions, each mutation-checked to confirm it is not vacuous:
  - the no-look-ahead refusal reports boundary and named offenders on **both** the
    `available_at` and `index` paths (setting `_SAMPLE_LIMIT = 0` fails three tests);
  - the child-boundary escape reports `axis` and the offending label;
  - a rejected nested-research child reports `error_code` (reverting the widened `except`
    turns the rejection into an uncaught error).
- `qlibx errors QLIBX_BOUNDARY_LOOK_AHEAD` and
  `qlibx errors QLIBX_BOUNDARY_CHILD_AXIS` both answer with code-specific
  recovery, which is the gap that motivated the change.
- The existing bidirectional guard in `test_documentation.py` holds: every raised code has
  installed guidance and every documented code is reachable.
