# 168 — the Python door asks the judgments too

**Closes:** the open item record [`167`](167-explicit-runtime-ownership-and-boundaries.md) left
under "the two doors are still two doors" (review R7). **Branch:** `develop @ cd129b6f`.
**Campaign:** none. **Owner decision, 2026-09-08:** *the Python surface and the CLI differ only
in their interface; they must go through the same process. The CLI asking `check` while Python
does not is a defect.* **Scope:** `flow/judgments.py`, `flow/orchestration.py`, `cli/run.py`,
`cli/check.py`, one CLI test, the sample test and one comment in the sample journey.

## Why this exists

Record `087` made `vqapr run` ask the eight judgments `vqapr check` asks, so that a green `run`
means what a green `check` means. It put that gate in the CLI verb. The public `preflight_run`
— the door a Python caller, and the shipped sample's own `execute`, walk through — kept freezing
without asking, so the parity `087` bought held between two CLI verbs and stopped at the
facade. Record `167` met the consequence: the registered sample was refused by `vqapr run` and
executed by `journey.execute` on the same declaration, and the sample's horizon had to move
before the CLI would accept it. That fixed the sample and left the structure.

## What changed

- **`require_judged(definition, workspace)`** (`flow/judgments.py`) is the CLI's
  `_refuse_if_judged` moved beside the judgments it renders, asking them itself. Same refusal:
  stage `run.judgments`, family `INTENT`, the judgments' own `check.*` codes, and
  `run.check.judgment_blocked` for a judgment that could not answer. `JUDGMENT_STAGE` moved
  with it.
- **The public `preflight_run`** (`flow/orchestration.py`) calls it before the freeze. One
  process, two spellings: `vqapr run` calls this function with the workspace it opened, and so
  does a Python caller, and so does `journey.execute`. A refused run raises the `VqaprError`
  `check` renders, and nothing is frozen.
- **`vqapr run`** (`cli/run.py`) no longer asks the judgments itself; its `except (TypeError,
  ValueError)` around `preflight_run` already let `VqaprError` through on purpose, so the
  refusal reaches the envelope by the path that was there.
- **`vqapr check`** (`cli/check.py`) is the collecting form of the same judgments and asks them
  in its own phase loop, so its `preflight` phase now calls the freeze alone
  (`flow.preflight.preflight_run`) on the workspace it already opened. Through the public door
  it would have asked the judgments a second time and rendered a blocked judgment twice, once as
  `blocked` and once as a failure. `--jobs` workers likewise freeze alone: the parent judged
  before it spawned them.
- **Tests.** `test_the_python_door_refuses_what_check_refuses` registers the look-ahead run of
  `docs/issues/archive/015` and proves `preflight_run` from `vqapr.public` refuses it under
  `run.judgments` with a code `check` published, leaving no record;
  `test_the_python_door_freezes_what_check_passes` proves the gate is not a wall. The sample test
  from record `167` now asks the public door instead of the judgments directly, because the
  public door is what `execute` uses.

## What this changes for a Python caller

A definition the judgments refuse — a look-ahead, an account mode contradicting its opening
positions, an unregistered dataset, a lookback the dataset cannot cover — now raises
`VqaprError` from `preflight_run` before any `TypeError` or `ValueError` the freeze would have
raised for it. The freeze's own refusals are unchanged for a definition the judgments accept.
Every judgment is answered against the registered workspace, so an in-process definition must
name registered components, which the freeze already required.

## Validation

- `uv run ruff check src/` and on the two edited tests: clean; `ruff format` applied to
  `cli/check.py` (one blank line) and checked on the rest.
- Focused run (`tests/cli tests/flow tests/qa/test_check_collects.py tests/characterization
  tests/boundaries tests/acceptance tests/report`): 654 passed and one expected failure, the
  refusal-code baseline noticing that `run.check.judgment_blocked` moved from `cli/run.py` to
  `flow/judgments.py`; the baseline was regenerated deliberately and its diff is that move plus
  line drift.
- `test_all` on the tree with this change alone: 1451 passed, 2 failed -- showcases 006 and 008,
  refused by `check.lookback.uncovered` through the door this record opened. Their ensemble runs
  opened with their members, so the first ensemble decision read an empty allocation window; the
  showcases were the sample's defect again, and the owner chose to keep the judgment and move the
  horizon (the change beside this one, in the showcase commit). `test_all` after that:
  **1453 passed** in 375 s (record `169`'s run).
