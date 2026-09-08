# 189 — The dead-code pass is silent again, and the whitelist points where the code moved

**Date:** 2026-09-08. **Branch:** `develop` (post-merge cleanup of the
`redesign/component-eventloop` campaign; no plan of its own). **Reported by:** `uv run vulture`,
run after the merge because the pass is declared for *"before a cleanup task, not on every
edit"* and a merge of 201 files is that occasion.

## Why

Record `170` left `uv run vulture` with no output, and that silence is what makes the pass worth
running: the first name it reports is a finding, not noise to sift. After the campaign merged it
reported four names. Three of them were the campaign's own residue and one was never a finding at
all -- and the whitelist that is supposed to tell those apart cited two paths that no longer
exist, because M6 dissolved `evidence/` and record `172` moved the sample into the package. A
whitelist whose comments rot is worse than one that makes the reader grep (its own words), so
the paths are part of the finding.

## What

**Two production members deleted.**

- `Materialized.execution_dataset_id` (`agent/sample/materialize.py`). Written at construction
  from `EXECUTION_ID`, read nowhere. It dates from when the execution table was its own
  registration (`execution_inputs:`); record `185` made it a dataset like any other, and what a
  caller of `materialize()` needs from it is the declaration path, which is what `cli/new.py`
  reads. The `EXECUTION_ID` constant stays -- it names the dataset in the declaration the
  materializer writes, and three tests import it through `tests/sample/journey.py`.
- `SimulationStage.VALUATION` (`flow/artifacts.py`). No `guard` or `due_boundary` is entered
  with it, and nothing parses or iterates `SimulationStage`, so no persisted record can name a
  stage the enum no longer has. Valuation is guarded by the four `DUE_VALUATION_*` /
  `DUE_ACCOUNT_MARK` stages inside the due path (record `148`) and monitoring by `MONITORING`,
  which is used; this member is what was left when valuation stopped being a scheduled event.

**Two test names whitelisted, because they are not findings.** `Role.STRATEGY_CALLBACK` and
`Role.VALUATION` in `tests/test_a_validation_error_is_a_refusal.py` are a closed-set enum
pydantic matches a payload's *string* against, and the test asserts the refusal lists both
(`"strategy_callback, valuation"` in `failure.requirement`). Both are load-bearing and neither is
ever named in code -- the third shape the whitelist's header already describes.

**Three stale citations corrected.** `src/vqapr/evidence/artifacts.py` -> `src/vqapr/flow/
artifacts.py` for `FailureObservation`, `AccountCommitEvidence` and `MarkEvidence` (M6, record
`188`), and `SampleExchange` now cites `src/vqapr/agent/sample/exchange.py` with its real
registrar: `materialize.py` writes the literal `"SampleExchange"` into the declaration and the
loader resolves the class from that string. The old comment named `tests/sample/journey.py` and
a path deleted by record `172`.

## Trade-offs

Deleting a member of a closed vocabulary is the reversible half of a decision: if a later change
wants a `simulation.valuation` stage it adds one, and nothing read the old value in between. The
alternative -- whitelisting it as "reserved" -- was rejected because the whitelist's own rule is
that everything in it names a caller, and a reserved-for-later name has none.

## Validation

- `uv run vulture`: no output.
- `uv run ruff check src/`: clean. `uv run pyright`: 0 errors.
- `uv run pytest tests/ -q -m ""` (test_all): 1603 passed.
