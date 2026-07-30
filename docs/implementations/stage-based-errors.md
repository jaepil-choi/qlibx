# Errors name the journey stage, not the kind of rule

Supersedes two earlier passes in this session (`error-code-tree.md`,
`public-and-internal-errors.md`), both removed. They reorganized the *taxonomy* and reduced
its size, but kept the wrong axis. Specifies PRD 5.6.

## Why this change exists

The previous vocabulary was seven kinds: `NOT_FOUND`, `MISSING`, `INVALID`, `BOUNDARY`,
`CONFLICT`, `CORRUPT`, `UNSUPPORTED`. Each answers *what kind of rule broke*. That is a
question the core can answer and the agent cannot use — receiving `INVALID` tells an agent
nothing about where in its own workflow it is stuck, so it has to reverse-engineer that
before it can act.

Worse, the model implied the core could prescribe the repair, and it cannot. A Strategy
failing on a text value in a numeric column can be repaired by casting inside the Strategy
or by preprocessing and re-registering the dataset. Both are legitimate; which is right
depends on whether that text is a data defect or a column that means something, and only the
user knows. A core that answers `INVALID` plus a single recovery line is guessing.

This is the division PRD 1.2 already set for capabilities — core reports, agent layer
resolves through skills — applied to errors, where the implementation had drifted from it.

## What changed

**The code is now the journey stage.** Eleven, taken from the PRD workflow rather than from
a taxonomy exercise:

```
ONBOARDING  PROJECT  DATA_REGISTRATION  UNIVERSE  STRATEGY_CONTRACT  STRATEGY_RUN
ALPHA  PORTFOLIO  EXECUTION  RESEARCH_RECORD  REPORTING
```

A stage selects a skill and bounds which repairs are legitimate. That is what makes it
actionable where a rule-kind was not.

**`action` became `expected`.** The field now states what the contract required, not what to
do about it. `expected="Membership is boolean and complete; absence of a row is not
non-membership."` reports; `"Run qlibx data register again"` prescribes, and prescribing is
the skill's job.

**Failures from user code pass through unclassified.** `errors.passthrough` carries the
original exception type and text verbatim:

```json
{"stage": "STRATEGY_RUN",
 "message": "TypeError: unsupported operand type(s) for -: 'str' and 'float'",
 "expected": "The Strategy callable runs on its bound inputs at every decision time.",
 "context": {"raised": "TypeError", "strategy_id": "reversal.v1", "decision_time": "2024-03-05"}}
```

Deciding whether someone else's `TypeError` is "invalid" or "corrupt" is unanswerable from
inside the call and discards the one description that was accurate.

**`UNIVERSE` became its own stage.** Universe is the requirement every Strategy inherits, so
its standard — boolean, point-in-time, unique per `(available_at, ticker)`, complete — is
checked at registration and reported against its own step rather than folded into data
registration or discovered later during a run.

**`qlibx errors <stage>` answers with the stage's responsibility and its skill name**, not a
recovery. `ERROR_GUIDANCE` is now generated from `errors.STAGES`.

## The stage has to survive to where the check runs

`config.py` serves four different steps, so a malformed YAML means something different in
each. `for_stage(...)` binds its readers once per calling module:

```python
read_yaml, require_mapping, require_string, require_strings = for_stage("STRATEGY_CONTRACT")
```

Seventy call sites keep their existing form and the stage is declared once, visibly, at the
top of the module that owns it.

A duplicate YAML key is found inside PyYAML's own constructor, where no argument can reach.
`_loader_for(stage)` returns a loader subclass carrying the stage, so that failure still
reports the step the agent was working on. A test asserts this specifically, because it is
the one place the threading could silently fall back to a default.

## Invariants

- `test_every_raise_names_a_declared_journey_stage` — a raise naming an undeclared stage
  fails with file and line. Non-literal stages are permitted and expected (`config`, `errors`
  serve several steps), but at least 80% of raises must name theirs directly, so threading
  cannot quietly become the norm.
- `test_every_public_failure_states_what_the_contract_expected` — every `QlibxError(...)`
  passes `expected`, checked at the call site.
- `test_the_core_does_not_prescribe_a_repair_workflow` — `expected` may not contain a CLI
  command or send the agent to interview the user. Stating what qlibx will *not* do
  ("qlibx does not aggregate") is reporting and is allowed.
- `test_the_stages_are_the_user_journey_in_order` — the list, in order.
- `test_internal_failures_stay_out_of_the_agent_vocabulary` — unchanged from the previous
  pass; `QlibxInternalError` has no stage and no `expected`.

## Trade-offs

- **`PORTFOLIO` and `REPORTING` are declared but not yet raised.** Those modules still use
  bare `ValueError`. Unlike codes, stages are a product taxonomy declared ahead of use, so
  there is deliberately no reachability test for them.
- **Two stages are judgement calls.** `extensions` is `ONBOARDING` (adding capability to the
  project) and `profiles` is `EXECUTION` (the profile exists to run a backtest). Both could
  be argued the other way; they are recorded here so the next reader knows they were chosen
  rather than defaulted.
- **The first prescription check was too broad.** It flagged `"Use table or matrix."`, which
  states the contract rather than prescribing a workflow. Narrowed to CLI commands and
  user-interview instructions after the false positives showed the rule was wrong, not the
  code.

## Validation

- `uv run ruff check .` and `uv run ruff format --check .` — clean.
- `uv run pytest` — `142 passed, 1 failed`, the failure being the pre-existing Windows
  `cp949` console-codec error in `tests/acceptance/test_p0_p1_agent_journey.py`.
- `qlibx errors <stage>` checked directly, plus a universe rejection and a passed-through
  `TypeError` serialized to confirm the shape.
- The generated agent skill now documents the stage list and states, with the string-column
  example, that qlibx does not choose the repair.

## Still open

`optimization.py` (22), `alpha/*` operations (23) and a handful elsewhere still raise bare
`ValueError`. The question at each site is now sharper than "convert it": *which stage is the
caller in, and could they have caused this?* Sites that no journey stage covers are internal
defects and should stay out of the agent vocabulary.
