# 181 — The four readers share one base, and a constraint remembers

**Date:** 2026-09-08. **Branch:** `redesign/component-eventloop` (campaign M1; plan
`.agent/plans/active/component-eventloop-redesign.md`). **Review:**
`docs/code-review/2026-09-08-four-readers-one-loop-and-the-missing-shapes.md` §1, §8-5.

## Why

The review found that the four authored kinds -- DataModel, StrategyModel, Constraint, Exchange
-- write one pattern in four spellings: each *declares what it reads*, is *handed a bounded view
at one instant*, and *returns one judgment*. Three of them used the same `inputs()` declaration,
the same `requirements_for` fan-out and the same `_DeclaredReads` mixin, and still had no common
base: `Model` held DataModel and StrategyModel, and `Constraint` stood outside it with
`inputs()` and `requirements()` copied verbatim (`authoring.py:1133-1153`). The docstring gave
the reason: *"a constraint is a stateless predicate that must not have any [memory]"*.

The owner ruled that premise wrong (2026-09-08): *"constraint가 기억이 필요없다는 전제 자체가
잘못된거야. 3회 이상 위반하면 out 이라는 constraint가 있을 수도 있잖아."* A rule that counts
remembers. And the common concept the four share, in the owner's words, is that they are all
*objects called back on an event with that event's time*.

## What

**1/2 — `Component` (`37acf4db`).** `authoring.Model` is renamed `Component` and is the base of
`DataModel`, `StrategyModel` and `Constraint`. It carries `memory`, `inputs()` and
`requirements()` once; `Constraint`'s copies are deleted. `Component` is exported from
`vqapr.public` and `vqapr.authoring`. The `Exchange` protocol is not yet a subclass -- it still
declares its reads with `execution_requirements()` and receives its inputs as arguments rather
than a `Call`; it joins in M4, when the execution table becomes a registered dataset
(§8-2 of the review, resolved the same day).

**2/2 — committed constraint memory (this commit).** A `memory` attribute nobody commits would
be a trap: a constraint that counted would count in-process and lose the count on any
restore. So the run state now commits a constraint's memory the way it commits the Strategy's:

- `AcceptedRunState.constraint_state_refs: Mapping[str, ModelStateRef]` -- one ref per
  constraint id, into the same `_model_states` map, proved the same way. The Strategy's
  `current_model_state_ref` is unchanged; it is the one with a payload.
- `RunStateRepository(initial_constraint_memory=...)` seeds the refs from what each constraint
  holds as loaded. `orchestration._run_strategy` passes `{id: constraint.memory}`;
  `SimulationFlow.__init__` refuses a state whose refs are not exactly the loaded constraints.
- `prepare_callback(constraint_memory=...)` and `prepare_monitoring(constraint_memory=...)`
  take what the callbacks left; every other `prepare_*` carries the refs over unchanged.
- `FlowContext.visible_constraint_memory()` / `restore_constraint_memory()` /
  `candidate_constraint_memory()` are the one implementation both phases use.
  `CallbackPhase.dispatch` restores before the projections and captures after them; the
  candidate rides on the callback publication and a failed callback restores the instances.
  `ValuationPhase._monitor` restores before `project`+`monitor` at the fill instant and
  publishes what they left with the findings.
- `CallbackPhase.load_visible_strategy_state` became `load_visible_state`: the run's first act
  restores every component's memory, not only the Strategy's.

`tests/flow/test_a_constraint_remembers.py` runs a "three strikes" rule through four sessions:
what `monitor` counted is what the next `project` reads, the count is on the final root and not
only on the instance, and a callback that fails after `project` mutated the memory leaves the
root and the instance as they were.

## Trade-offs

- **No payload for constraints.** `prepare_model_state(memory, b"")`. A constraint with a fitted
  object would need `save_payload`/`load_payload` like a Strategy; nothing asks for it yet.
- **Initial constraint memory is not frozen into `FrozenStrategy`.** It is whatever the
  constructor left, and the constructor's inputs are the `ComponentRef.config` the fingerprint
  already folds. Freezing it separately would fold the same fact twice.
- **`project` runs twice per session** (callback and fill instant, record `148`); both see the
  memory monitoring committed on earlier sessions, and monitoring's own write lands after its
  projection. The test states this so a reader of `projected_with == [0, 0, 1, 1, ...]` is not
  surprised.
- **`Generic[CallT, JudgmentT]` was not added to `Component`.** Constraint has two judgments
  (`project`, `monitor`), so a single judgment parameter would not fit it; the handler side's
  typing comes with `EventLoop` in M2.

## Validation

- `uv run pytest tests/ -q` (fast set): see the commit; the two scaffold tests that still
  expected `Decimal` from a scaffold record 174 changed to return `float` were fixed in
  `9aa2e8bf` beforehand.
- `uv run ruff check src/`: clean.
- `uv run pyright`: 184 errors, unchanged from the M0 baseline (basic).
- `test_all` is run at the M7 merge gate (the worktree has no `data/DW`).
