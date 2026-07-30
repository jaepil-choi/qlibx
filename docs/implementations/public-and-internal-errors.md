# Two kinds of failure, and seven public codes

## Why this change exists

Errors in qlibx are a protocol with the agent layer. That was stated but not modeled:

- **The model was in three pieces.** `QlibxError` in `errors.py`, the code as a bare `str`
  at 148 raise sites, and `ERROR_GUIDANCE` as a 590-line table in `documentation.py`. What
  held them together was one AST-scanning test — a lint, not a model. `QlibxError("BANANA",
  ...)` was constructible.
- **Internal defects used the agent protocol.** `run_signed_execution` reconciling its own
  composite/baseline/active books — `C = B + A does not hold within tolerance` — raised a
  stable code with a recovery. The caller neither caused a book disagreement nor can repair
  one. It was a defect report wearing an agent contract.
- **The vocabulary was 126 codes and duplicating itself.** `QlibxError` already carries
  `action`, written where the check ran. `ERROR_GUIDANCE[code].recovery` carried the same
  thing per code. Forcing the static table to be as specific as the raise site meant every
  distinct raise needed its own code — which is exactly how 126 happened.

## What the model is now

```python
class QlibxError(RuntimeError):        # agent protocol
    code: ErrorCode                    # one of seven
    message: str                       # what happened
    action: str                        # required, not optional
    context: dict                      # the evidence
    requires_user_confirmation: bool

class QlibxInternalError(RuntimeError):  # a defect
    message: str
    context: dict                        # no code, no action
```

`action` is required because it is what makes a failure public. A failure that cannot say
what to do next is an internal failure wearing the wrong type — that sentence is now a
constructor signature rather than a convention.

**Seven codes, and they are the whole public vocabulary:**

```
NOT_FOUND  MISSING  INVALID  BOUNDARY  CONFLICT  CORRUPT  UNSUPPORTED
```

The code names the *kind*. Everything about the occurrence — what happened, what to do, the
evidence — lives on the error, written by the check that ran. `ERROR_GUIDANCE` went from 590
lines to seven entries re-exported from `errors.py`, so the model has one home.

This is safe because **nothing in qlibx branches on a code** — verified, zero sites. Codes
are a lookup key for the agent, and the agent already receives `action` and `context` with
the failure.

## Behavior change

Every code is renamed, again, and this time collapsed 126 → 7. Taken deliberately for the
reason above; the previous pass had reorganized the names without removing the duplication
that generated them.

`to_dict()` gains `requires_user_confirmation`, which moved from the static table to the
eight raise sites that own it. It is a property of the situation, not of the code.

The two signed-execution reconciliation identities now raise `QlibxInternalError` and are
gone from the agent vocabulary.

## What is lost, and it is real

A stable identifier per failure. A runbook could previously say "on
`QLIBX_BOUNDARY_LOOK_AHEAD`, do X"; now it must match on `code == "BOUNDARY"` plus something
in `message` or `context`. This was weighed and chosen: no code was ever branched on, and
the per-failure guidance the identifiers carried is now on the error itself, where it is
also available to a caller who never looks anything up.

Tests that asserted a specific code are correspondingly weaker, so the ones that matter now
assert on `context` instead — the look-ahead test pins the boundary and the offending
timestamps rather than a code string, which is a better test than it was.

## Invariants

- `test_the_public_vocabulary_is_the_seven_codes_and_nothing_else` — a raise using an
  undeclared code fails with its file and line; a declared code nothing raises also fails.
- `test_every_public_failure_says_what_to_do_next` — AST-checks that every `QlibxError(...)`
  passes `action`. Checked at the call site rather than trusted to the signature, because a
  positional argument would satisfy a type checker while leaving this to habit.
- `test_internal_failures_stay_out_of_the_agent_vocabulary` — `QlibxInternalError` is not a
  `QlibxError`, exposes no `code` or `action`, and `execution.py` raises exactly two.

## Trade-offs

- **Seven may be too coarse for telemetry.** Grouping failures by code now yields seven
  buckets. If that turns out to matter, the fix is a `kind` field in `context`, not more
  codes — the codes are the caller's action, and `context` is where the specifics live.
- **`unknown_name()` lost its code parameter**, since NOT_FOUND is the only answer it can
  give. Ten call sites simplified.
- **The migration was scripted**, and one insertion landed inside a `list.extend(...)` call
  in `skill.py` rather than the intended raise. The test suite caught it as a `TypeError`.
  Machine edits to 148 sites need the suite as the check, not review alone.

## Validation

- `uv run ruff check .` and `uv run ruff format --check .` — clean.
- `uv run pytest` — `140 passed, 1 failed`, matching the pre-change count. The failure is the
  pre-existing Windows `cp949` console-codec error in
  `tests/acceptance/test_p0_p1_agent_journey.py`.
- `qlibx errors` and `qlibx errors <code>` checked directly; a public failure and an internal
  failure serialized side by side to confirm the internal one carries no code and no action.

## Still open

`optimization.py` (22), `alpha/*` (23) and a handful elsewhere still raise bare `ValueError`.
Under this model that is no longer simply debt to convert: each is either an agent-facing
contract failure (should be `QlibxError`) or a programmer error (should be
`QlibxInternalError` or stay a `ValueError`). Deciding which is a separate pass, and the
question to ask at each site is the one that defines the split — *could the caller have
caused this, and can they act on it?*
