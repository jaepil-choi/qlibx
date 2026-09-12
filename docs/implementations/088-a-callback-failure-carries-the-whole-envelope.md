# 088 — A callback failure carries the whole envelope

**Closes:** `docs/issues/archive/016-a-callback-failure-drops-half-the-envelope.md`.
**Branch:** `fix/016-callback-envelope`.

## Why this change exists

The installed skill states the guarantee without qualification:

> Every entry carries `code`, `source`, `requirement`, `observed`, `fix` and `explain`

and tells the reader which to use first:

> read `fix` first. It is the sentence that fixes *this* occurrence

A failure raised inside the strategy callback delivered four of the six. `fix`, `explain` and
`source` were absent entirely — including the one field the skill names as the one to read first —
and `requirement` degraded to *"the guarded boundary must complete without raising"*, which is a
statement about this package's own plumbing rather than about anything the author did.

The journey hit it twice, and the reporter's own summary was that *"three further entries are the
same defect three times"*: issue 016 is the shared cause, and 018 and 019 are what a reader hits
because of it.

## What changed

`SimulationFailure.as_dict` (`src/vqapr/evidence/artifacts.py`) synthesizes an envelope entry when
the cause is an ordinary exception rather than a `VqaprError`. That synthesis produced four keys.
It now produces all six, through three additions:

- **`_requirement_for(stage)`** — for the four `simulation.callback.*` stages the requirement is now
  *"the strategy callback must return without raising"*. The old sentence described the framework's
  guard; this one describes what was required of the code that actually raised. Non-callback stages
  keep the original wording, because there the guard genuinely is the subject.
- **`_fix_for(stage, cause)`** — the field the skill says to read first, previously absent. An
  arbitrary exception carries no repair advice, so the best available instruction is *where to
  look*: the author's callback for a callback stage, the run's own record otherwise. It names the
  exception type, and it states that re-registration replaces in place, so an author does not
  conclude they need a new component id to retry (`docs/issues/archive/009`).
- **`_EXPLAIN_BY_STAGE`** — maps the callback stages onto **existing** topics:
  `COMPONENT_CONTRACT` for state/window/intent, `PUBLICATION` for publication. Anything unmapped
  falls back to `RUN_PRECONDITION`.

`source` is emitted as `FailureSource(file=None).as_dict()`. The boundary genuinely does not know
which file the author's component lives in — it holds a loaded object, not a path — so the field is
present and honestly empty rather than absent. A reader iterating the six fields no longer has to
special-case its absence.

**No new `ExplainTopic` member, and no new SKILL.md section.**
`tests/characterization/test_explain_topics.py` pins topics and `### Recovering from:` sections to
each other in both directions, so inventing a topic here would have required writing its section in
the same commit. Both topics used already exist and already resolve.

**The refusal-code baseline is unchanged.** These codes are synthesized at runtime from the stage
and the exception type (`simulation.callback.intent.ValueError`), so they never entered the static
inventory that `tests/characterization/test_refusal_codes.py` folds. Confirmed by running it: 6
passed, no regeneration needed.

**A `VqaprError` cause is still passed through untouched.** It already carries all six, and
re-coding it would rename a defect the reader may already have handling for. Asserted.

## Validation

**Gate:** fast suite + `tests/qa/test_refusal_envelope_six_fields.py` +
`tests/characterization/test_explain_topics.py` + `tests/flow/test_session_callbacks.py` +
`tests/characterization/test_refusal_codes.py`.

| check | result |
|---|---|
| the four named gate files | 17 passed |
| `tests/qa/test_callback_failure_carries_the_whole_envelope.py` (new) | 6 passed |
| `tests/characterization/test_refusal_codes.py` | 6 passed, baseline unchanged |
| full fast suite | **1350 passed, 14 deselected** (1344 before, +6 new) |

The new tests assert the merge condition directly, using **the journey's own two failure messages
verbatim** — `"invested must be greater than zero and no greater than one"` and
`"decide() emitted undeclared diagnostic tables: ['ff3.formation']"` — rather than a synthetic
stand-in, so the regression is pinned to the thing that was actually reported:

1. Both messages produce entries with all six fields non-empty, and the author's own message
   survives intact in `observed`.
2. `requirement` no longer contains "guarded boundary" and does mention the callback.
3. `fix` names what was raised, says where to look, and says registration replaces in place.
4. `explain` resolves to a real topic, checked per stage.
5. A `VqaprError` cause passes through with its own code, fix and topic unchanged.
