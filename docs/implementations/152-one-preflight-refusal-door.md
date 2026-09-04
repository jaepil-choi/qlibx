# 152 — one preflight refusal door: the step is named and the cause travels

**Closes:** `docs/issues/076`. **Branch:** `step-02-076-one-preflight-door`, off `develop @
aded3145`. **Campaign:** `docs/refactoring/2026-09-04-the-one-shape-campaign.md`, Step 2.
**Authority:** the owner, 2026-09-04.

## Why this exists

Preflight round-trips a strategy's payload on fresh instances before the first callback --
`save_payload`, `load_payload` on a second instance with those bytes, `save_payload` again, bytes
compared. That is a real contract and preflight is the right time to prove it. Three things made
it unreadable when it refused, and the scenario testbed's run 4 hit all three at once (F-004):

- **One `try` around three steps.** Every exception became the same constant string, "strategy
  initial payload for 'ffn_k0' cannot be staged". An author with a `save_payload` and a
  `load_payload` could not tell which one to open.
- **The cause was dropped.** `_validate_initial_model_state` raised `from error`, correctly, and
  then `cli/check.py::_from_python` rendered `f"{type(error).__name__}: {error}"` -- the outer
  exception only. The `EOFError: Ran out of input` that was the actual reason never reached the
  envelope. The author found it in `.vqapr/diagnostics/unhandled.txt`.
- **Two doors for one judgment.** `check` caught the `ValueError` and rendered a bounded refusal;
  `cli/run.py::run` called `preflight_run` *outside* its `try`, so the same `ValueError` from the
  same function left the same package as `stage: "unhandled"`, `failures: []`, `family: null`.
  That tells an agent the framework broke when the truth is the strategy was wrong. The `012`/`015`
  family: `run`'s own docstring promises a green `run` means what a green `check` means, and a red
  one did not.

## What changed

- `cli/run.py::preflight_refusal(phase, error, target) -> Failure` — `_from_python` moved out of
  `cli/check.py` under a name that says what it renders, beside `_refuse_if_judged` and
  `refuse_a_path`, the two refusal renderers `check` already imports from this module. Its
  `observed` is now a `__cause__` chain built by `_chain()`: `"ValueError: strategy initial
  payload for 'x' cannot be staged: load_payload of those bytes on a second fresh instance <-
  EOFError: Ran out of input"`. Only `__cause__` is followed, never `__context__` — an explicit
  `raise ... from` is an author saying the two are one story. Bounded at `_MAX_CAUSE_LINKS = 4`
  hops, then `...`, so `observed` cannot grow with a user's own nesting.
- `cli/run.py::run` wraps `preflight_run` in `try` and re-raises `(TypeError, ValueError)` as
  `VqaprError(stage=PREFLIGHT_STAGE, family=INTENT, failures=[preflight_refusal(...)])`.
  `PREFLIGHT_STAGE` is `"run.check"`, `check`'s own stage, and the codes are `check`'s own codes.
  `VqaprError` and `InputError` are deliberately not caught: both already carry a bounded body.
- `flow/preflight.py::_validate_initial_model_state` is three `try` blocks, each naming its step
  in the message — `save_payload on a fresh instance` / `load_payload of those bytes on a second
  fresh instance` / `save_payload again` — and the byte comparison is a fourth sentence,
  `save_payload again wrote different bytes`, raised outside any `try` because nothing raised.
- `authoring.py`: `save_payload` states the three-step round trip and that it must therefore be
  deterministic (no timestamp, no `id()`, no unordered set iteration); `load_payload` states that
  a class with nothing to save yet must accept an **empty** source, because the default
  `save_payload` writes no bytes.
- `SKILL.md`, in the `self.memory` paragraph: the same contract in the skill's own voice.

## Decisions

- **`cli/run.py`, not `flow/preflight.py` or `cli/envelope.py`.** The campaign left the location
  open. The codes are `run.check.*` — a CLI stage — so `flow/` is the wrong altitude, and
  `envelope.py` renders envelopes rather than building `Failure`s. `cli/run.py` already owns the
  two refusal renderers `check.py` imports (`refuse_a_path`, and `JUDGMENT_STAGE` beside
  `_refuse_if_judged`), and the import direction `check -> run` already exists, so this adds no
  edge to the graph.
- **`run` catches `(TypeError, ValueError)`, and that is the whole escape set.** Checked rather
  than assumed: every `raise` in `flow/preflight.py` is one of those two or a `VqaprError`, and
  user code reached through `load_strategy_model` comes back already bounded — a strategy whose
  `inputs()` raises `RuntimeError` leaves `run` as `stage: "component.load"`, not `unhandled`.
  So the narrower catch leaves no parity hole against `check`'s bare `except Exception`, and it
  does not reclassify a framework bug as the user's fault.
- **The scaffold is not touched.** It emits no payload methods, so a sentence there would describe
  a contract the generated file does not participate in. The two docstrings and the skill are
  where an author who writes them will read.
- **The refusal-code baseline was regenerated deliberately.** The gate is keyed on `(code, file)`
  and fired exactly as designed: `run.check.declaration_invalid` and `run.check.preflight_refused`
  moved `cli/check.py -> cli/run.py`. Nothing added, nothing removed.

## Validation

- `tests/cli/test_a_preflight_refusal_names_its_step.py`, five tests over a strategy whose
  `load_payload` calls `pickle.load` on the empty source the default `save_payload` produced:
  `check` names the step and carries `EOFError: Ran out of input`; `run` answers `stage:
  "run.check"` and `run.check.preflight_refused` rather than `unhandled`; both verbs render
  `code`, `requirement`, `observed`, `fix`, `explain` and `source.key_path` **identically**; the
  six guaranteed fields are present; a non-deterministic `save_payload` is named as the third step
  with no cause to chain.
- `tests/characterization/` green after the deliberate regeneration; `tests/cli/`,
  `tests/flow/test_preflight.py`, `tests/boundaries/` — 269 passed.
- `ruff check src/` clean; `vulture` at its two-item baseline. Full fast suite: see the merge
  commit.
