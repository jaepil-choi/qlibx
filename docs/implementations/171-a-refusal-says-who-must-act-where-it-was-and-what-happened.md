# 171 — A refusal says who must act (status), where it was (stage), and what happened (cause)

**Closes:** the owner's 2026-09-08 decision on the refusal vocabulary, made while reviewing
record `170`'s open items. **Branch:** `develop`, on top of record `170`. **Breaking:** every
refusal code, the `stage` values, and the envelope's `family` and `explain` fields change; an
agent that branched on a 0.6.0 code has to be re-pointed. Pre-1.0, by decision.

## Why

The 0.6.0 vocabulary was 113 codes shaped `<where>.<where>.<what>` (`dataset.register.schema.
field_missing`), with the abstract class an agent needs first -- is this mine to fix, or
upstream's? -- living in a separate `explain` field of seven topics, and a third "where"
(`FailureFamily`) beside `stage`. Three classifications, hand-kept, none of them the one an
agent branches on. The owner's ruling, in their words: *404는 페이지 없음 503은 서버 오류인 것처럼*
-- the code's class must carry meaning the way HTTP's first digit does, separating the
framework's fault from the user's, and a registration that lacked a requirement from a check
that found the declaration and the data disagreeing.

And, because the taxonomy cannot be proven MECE in beta: *에러 메시지에 상관없이 원인을 그대로
실어야 해.* Every failure carries its cause, whole, so an agent can judge for itself.

## The three fields

- **`status`** (`Status`, `IntEnum`, HTTP's numbers): who must act. 4xx -- the submission is
  wrong; fix it before retrying: `400 invalid` (shape), `404 missing` (named, not there),
  `409 conflict` (disagrees with what is registered), `412 precondition` (well-formed, cannot
  run: the `check` judgments), `422 contract` (the user's code cannot be called, or returned
  something unusable), `423 locked`. 5xx -- the submission is fine; look at what ran:
  `500 internal` (the framework; file upstream), `502 crashed` (the user's own code raised;
  the gateway's upstream), `503 unavailable` (the machine: a file, a disk). An unknown `code`
  is handled as its status -- HTTP's rule that an unrecognised 4xx is a 400.
- **`stage`** (`Stage`, closed): which operation was under way at the raise site -- `usage`,
  `open`, `read`, `register`, `lookup`, `remove`, `write`, `load`, `check`, `freeze`, `run`,
  `record`. Replaces the free-form stage strings and absorbs `FailureFamily`.
- **`cause`** (`Cause`): `type`, `message`, `traceback` (the full text Python itself prints,
  never cut), `where` (innermost non-interpreter frame, `file:line (function)`), `origin`
  (`"user"` for a frame outside the package, `"framework"` inside it). A refusal raised without
  an exception still carries `where`/`origin`: the framework line that decided. `status_of(exc)`
  derives 502/500 from `origin`, which is how an exception nobody classified is rendered:
  one failure, code `unhandled`, whole traceback -- no more `stage: "unhandled", failures: []`.

`code` stays, as `<subject>.<detail>` with the class prefix gone. The full old→new table is
below.

## What changed where

- **`domain/errors.py`**: `Status`, `Stage`, `Cause` (`of(exc)`, `here(skip=)`), `status_of`,
  `unhandled(exc, stage=)`; `Failure` gains `status` and `cause` and loses `explain`; `Failure`
  without a `cause` captures its raise site in `__post_init__` (skipping this module's and the
  interpreter's frames, so a dataclass-generated `__init__` in `<string>` is not named);
  `VqaprError` loses `family`, gains `.status` (the most severe failure's), keeps `__reduce__`;
  `collector(stage)`. `ExplainTopic` and `FailureFamily` are deleted.
- **Raise sites** (113 static codes, four packages, migrated in parallel by ownership): every
  site names its `Status`, every site that has the exception in hand passes it as `cause`, every
  free-form stage string becomes a `Stage` member. The old `*_STAGE` module constants and the
  `SPAN_STAGE` cross-module assert are gone. The one `family`-driven branch in the loop
  (`callback.py`, DATA → window stage, else intent stage) was audited: every `VqaprError` that
  can reach it is a data refusal, so the other branch was dead and is gone.
- **`evidence/artifacts.py`**: `SimulationFailure` loses `family` and `SimulationFailureFamily`;
  a raise inside the user's callback renders as code `strategy.<stage>` (e.g.
  `strategy.callback.intent`) with `status_of(cause)` -- 502 when the innermost frame is the
  author's file -- and the exception as `cause`.
- **`flow/judgments.py`**: `judgments()` returns `(found, blocked)` as two lists of `Failure`;
  a blocked judgment is `judgment.blocked` with the whole cause and the status of the
  `VqaprError` that blocked it (a judge refused by `component.unregistered` is a 404, not a
  500), or `status_of` for a bare exception. `check` renders `blocked` through `as_dict()` and
  lists phases it never reached under a new `skipped` key, so no list mixes shapes.
- **`cli/envelope.py`**: an exception nobody classified is one `unhandled` failure with the
  whole traceback in `cause`; `stage` is the verb's (`main.py` maps each command to a `Stage`).
  The eight-line traceback cut and the file-instead-of-envelope rule are gone; the diagnostics
  file is still written, as an extra under `detail`. `UsageError` renders through a real
  `Failure` at last (`usage.rejected`, 400, stage `usage`); the reason it could not -- no
  `ExplainTopic` fit -- no longer exists. `InputError` codes are `argument.*` at stage `usage`.
- **`cli/run.py`**: a held run record is `record.live`, 423, a `VqaprError` at stage `record`;
  `preflight.refused` takes its status from its cause.
- **`vqapr.public`** exports `Status` and `Stage`, so a Python caller can branch on them.
- **`SKILL.md`**: "Reading vqapr's output" describes the three branches; seven topic sections
  became nine `### Recovering from: <number> <label>` sections, pinned both ways by
  `tests/characterization/test_status_sections.py`.
- **`tests/characterization/refusal_codes.py`** (schema `v2`): the baseline is `{status: [codes]}`
  plus `by_cause`, `runtime_codes`, `coverage_gap`, `unresolved` -- no file or line per code, so
  unrelated edits no longer churn it. A `code=` forwarded from an exception attribute or built
  from an exception's type name is a re-render, not a declaration. Regenerated once, after every
  site was migrated: 400:37, 404:12, 409:9, 412:14, 422:18, 423:2, 502:4, 503:12, by cause:3,
  unresolved: 0. No static 500 exists -- 500 only ever arrives through `status_of`.
- **`docs/vqapr-architecture.md`** §8.3 describes status/stage/cause.

## Mapping

| 0.6.0 code | stage | status | 0.7.0 code |
|---|---|---|---|
| `check.datamodel.output_registered` | check | 409 conflict | `datamodel.output_registered` |
| `check.dataset.unregistered` | check | 404 missing | `dataset.unregistered` |
| `check.execution.not_after_decision` | check | 412 precondition | `execution.not_after_decision` |
| `check.field.absent` | check | 404 missing | `field.absent` |
| `check.lookback.uncovered` | check | 412 precondition | `lookback.uncovered` |
| `check.period.uncovered` | check | 412 precondition | `period.uncovered` |
| `check.universe.absent` | check | 404 missing | `universe.absent` |
| `check.weights.mode_conflict` | check | 412 precondition | `weights.mode_conflict` |
| `check.weights.venue_conflict` | check | 412 precondition | `weights.venue_conflict` |
| `run.check.judgment_blocked` | check | by cause (500/502) | `judgment.blocked` |
| `component.conformance.load_failed` | register | 502 crashed | `component.import_failed` |
| `component.conformance.method_missing` | register | 422 contract | `component.method_missing` |
| `component.conformance.method_not_callable` | register | 422 contract | `component.method_not_callable` |
| `component.conformance.signature_invalid` | register | 422 contract | `component.signature_invalid` |
| `component.load.constraint_id_mismatch` | load | 422 contract | `component.constraint_id_mismatch` |
| `component.load.construction_failed` | load | 502 crashed | `component.construction_failed` |
| `component.load.execution_profile_invalid` | load | 422 contract | `component.execution_profile_invalid` |
| `component.load.module_invalid` | load | 422 contract | `component.module_invalid` |
| `component.load.requirements_failed` | load | 502 crashed | `component.requirements_failed` |
| `component.load.requirements_invalid` | load | 422 contract | `component.requirements_invalid` |
| `component.load.requirements_missing` | load | 422 contract | `component.requirements_missing` |
| `component.load.signature_invalid` | load | 422 contract | `component.signature_invalid` |
| `component.load.source_unreadable` | load | 503 unavailable | `component.source_unreadable` |
| `component.load.wrong_type` | load | 422 contract | `component.wrong_type` |
| `component.register.source_unreadable` | register | 503 unavailable | `component.source_unreadable` |
| `datamodel.compute.failed` | run | 502 crashed | `datamodel.compute_failed` |
| `datamodel.output.available_at_owned` | run | 422 contract | `datamodel.output.available_at_owned` |
| `datamodel.output.empty` | run | 422 contract | `datamodel.output.empty` |
| `datamodel.output.fields_invalid` | run | 422 contract | `datamodel.output.fields_invalid` |
| `datamodel.output.instrument_duplicate` | run | 422 contract | `datamodel.output.instrument_duplicate` |
| `datamodel.output.instrument_invalid` | run | 422 contract | `datamodel.output.instrument_invalid` |
| `datamodel.output.instrument_unrequested` | run | 422 contract | `datamodel.output.instrument_unrequested` |
| `datamodel.output.rows_invalid` | run | 422 contract | `datamodel.output.rows_invalid` |
| `datamodel.output.schema_mismatch` | run | 422 contract | `datamodel.output.schema_mismatch` |
| `datamodel.publish.chunk_failed` | record | 503 unavailable | `datamodel.chunk_failed` |
| `dataset.register.grain.undeclared` | register | 400 invalid | `dataset.grain_undeclared` |
| `dataset.register.key.duplicate` | register | 400 invalid | `dataset.key_duplicate` |
| `dataset.register.key.null` | register | 400 invalid | `dataset.key_null` |
| `dataset.register.schema.available_at_not_a_timestamp` | register | 400 invalid | `dataset.available_at_not_a_timestamp` |
| `dataset.register.schema.available_at_not_tz` | register | 400 invalid | `dataset.available_at_not_tz` |
| `dataset.register.schema.field_missing` | register | 400 invalid | `dataset.field_missing` |
| `dataset.register.schema.field_not_an_expression` | register | 400 invalid | `dataset.field_not_an_expression` |
| `dataset.register.schema.field_not_portable` | register | 400 invalid | `dataset.field_not_portable` |
| `dataset.register.schema.field_not_tz` | register | 400 invalid | `dataset.field_not_tz` |
| `dataset.register.schema.projection_unbindable` | register | 400 invalid | `dataset.projection_unbindable` |
| `dataset.register.schema.source_mismatch` | register | 400 invalid | `dataset.source_mismatch` |
| `dataset.register.span.absent` | register | 400 invalid | `dataset.span_absent` |
| `dataset.register.span.empty` | register | 400 invalid | `dataset.span_empty` |
| `dataset.register.value.not_finite` | register | 400 invalid | `dataset.value_not_finite` |
| `declaration.read.grain_undeclared` | register | 400 invalid | `declaration.grain_undeclared` |
| `declaration.read.key_missing` | register | 400 invalid | `declaration.key_missing` |
| `declaration.read.key_unknown` | register | 400 invalid | `declaration.key_unknown` |
| `declaration.read.run_fed_by_sibling` | register | 400 invalid | `declaration.run_fed_by_sibling` |
| `declaration.read.run_invalid` | register | 400 invalid | `declaration.run_invalid` |
| `declaration.read.unknown_section` | register | 400 invalid | `declaration.unknown_section` |
| `declaration.read.value_invalid` | register | 400 invalid | `declaration.value_invalid` |
| `declaration.read.value_not_permitted` | register | 400 invalid | `declaration.value_not_permitted` |
| `execution_input.register.key.duplicate` | register | 400 invalid | `execution_input.key_duplicate` |
| `execution_input.register.key.null` | register | 400 invalid | `execution_input.key_null` |
| `execution_input.register.price.invalid` | register | 400 invalid | `execution_input.price_invalid` |
| `execution_input.register.schema.field_type` | register | 400 invalid | `execution_input.field_type` |
| `execution_input.register.schema.price_type` | register | 400 invalid | `execution_input.price_type` |
| `model_window.requirement.undeclared` | run | 422 contract | `requirement.undeclared` |
| `observation_store.resolve.field_missing` | run | 404 missing | `store.field_missing` |
| `preflight.account.fractional_quantity` | freeze | 412 precondition | `account.fractional_quantity` |
| `preflight.account.holding_not_closable` | freeze | 412 precondition | `account.holding_not_closable` |
| `preflight.account.minimum_quantity` | freeze | 412 precondition | `account.minimum_quantity` |
| `preflight.account.mode` | freeze | 412 precondition | `account.mode` |
| `preflight.account.quantity_step` | freeze | 412 precondition | `account.quantity_step` |
| `preflight.account.unlisted_holding` | freeze | 412 precondition | `account.unlisted_holding` |
| `preflight.datamodel.output_registered` | freeze | 409 conflict | `datamodel.output_registered` |
| `preflight.execution.missing` | freeze | 404 missing | `execution.missing` |
| `preflight.execution.requirement_missing` | freeze | 404 missing | `execution.requirement_missing` |
| `preflight.execution.target_outside_horizon` | freeze | 412 precondition | `execution.target_outside_horizon` |
| `preflight.universe.unlisted_instrument` | freeze | 412 precondition | `universe.unlisted_instrument` |
| `preflight.universe.untradable_listing` | freeze | 412 precondition | `universe.untradable_listing` |
| `run.assembly.constraint_identity` | run | 409 conflict | `constraint.identity_mismatch` |
| `run.check.declaration_invalid` | check | 400 invalid | `run.declaration_invalid` |
| `run.check.preflight_refused` | freeze | by cause (500/502) | `preflight.refused` |
| `run.roster.unreadable` | read | 503 unavailable | `roster.unreadable` |
| `source.scan.conditional_positive.unreadable` | read | 503 unavailable | `source.conditional_positive_unreadable` |
| `source.scan.distinct.unreadable` | read | 503 unavailable | `source.distinct_unreadable` |
| `source.scan.execution_candidates.unreadable` | read | 503 unavailable | `source.execution_candidates_unreadable` |
| `source.scan.execution_snapshot.unreadable` | read | 503 unavailable | `source.execution_snapshot_unreadable` |
| `source.scan.finite.unreadable` | read | 503 unavailable | `source.finite_unreadable` |
| `source.scan.observations.unreadable` | read | 503 unavailable | `source.observations_unreadable` |
| `source.scan.path_missing` | read | 404 missing | `source.path_missing` |
| `source.scan.unreadable` | read | 503 unavailable | `source.unreadable` |
| `workspace.component.lookup.invalid` | lookup | 400 invalid | `component.reference_invalid` |
| `workspace.component.lookup.missing` | lookup | 404 missing | `component.unregistered` |
| `workspace.dataset.lookup.invalid` | lookup | 400 invalid | `dataset.reference_invalid` |
| `workspace.dataset.lookup.missing` | lookup | 404 missing | `dataset.unregistered` |
| `workspace.dataset.register.conflict` | register | 409 conflict | `dataset.registered` |
| `workspace.dataset.register.source_conflict` | register | 409 conflict | `dataset.source_conflict` |
| `workspace.dataset.register.source_mismatch` | register | 409 conflict | `dataset.source_mismatch` |
| `workspace.execution_input.lookup.invalid` | lookup | 400 invalid | `execution_input.reference_invalid` |
| `workspace.execution_input.lookup.missing` | lookup | 404 missing | `execution_input.unregistered` |
| `workspace.execution_input.register.conflict` | register | 409 conflict | `execution_input.registered` |
| `workspace.execution_input.register.source_conflict` | register | 409 conflict | `execution_input.source_conflict` |
| `workspace.instruments.unreadable` | read | 503 unavailable | `roster.unreadable` |
| `workspace.open.invalid` | open | 400 invalid | `workspace.invalid` |
| `workspace.open.missing` | open | 404 missing | `workspace.missing` |
| `workspace.open.unreadable` | open | 503 unavailable | `workspace.unreadable` |
| `workspace.remove.referenced` | remove | 409 conflict | `remove.referenced` |
| `workspace.remove.unsupported_kind` | remove | 400 invalid | `remove.unsupported_kind` |
| `workspace.run.register.conflict` | register | 409 conflict | `run.registered` |
| `workspace.run.register.invalid` | register | 400 invalid | `run.invalid` |
| `workspace.run.register.missing` | lookup | 404 missing | `run.unregistered` |
| `workspace.run.register.reference` | register | 400 invalid | `run.reference_invalid` |
| `workspace.source.lookup.invalid` | lookup | 400 invalid | `source.reference_invalid` |
| `workspace.source.lookup.missing` | lookup | 404 missing | `source.unregistered` |
| `workspace.write.failed` | write | 503 unavailable | `workspace.write_failed` |
| `workspace.write.locked` | write | 423 locked | `workspace.locked` |
| `cli.input.file_missing` | usage | 404 missing | `argument.file_missing` |
| `cli.input.file_unreadable` | usage | 503 unavailable | `argument.file_unreadable` |
| `cli.input.not_a_mapping` | usage | 400 invalid | `argument.not_a_mapping` |
| `cli.input.file_exists` | usage | 409 conflict | `argument.file_exists` |
| `cli.input.keys_missing` | usage | 400 invalid | `argument.keys_missing` |
| `cli.input.value_invalid` | usage | 400 invalid | `argument.value_invalid` |
| `cli.usage.rejected` | usage | 400 invalid | `usage.rejected` |
| `simulation.<stage>.<ExceptionName> (dynamic, evidence/artifacts.py)` | run | by cause (500/502) | `strategy.<SimulationStage value without the 'simulation.' prefix, e.g. strategy.callback.intent>` |
| `RunRecordLive (cli/run.py _held_record, currently an InputError)` | record | 423 locked | `record.live` |
| (new) `vqapr skill` refusals | usage | 500 `argument.skill_empty`, 404 `argument.no_git_root`, 400 `argument.unknown_action` | — |
| `run.check.judgment_blocked` (status) | check | the blocking `VqaprError`'s status, else by cause | `judgment.blocked` |

## What an agent sees now

`vqapr check nothing` in an empty directory, one failure, abridged:

```json
{"stage": "check", "failures": [{
  "code": "workspace.missing", "status": 404,
  "requirement": "workspace must exist at .../.vqapr/workspace.yaml",
  "observed": "path does not exist",
  "fix": "run `vqapr register <declaration>.yaml` in this directory, ...",
  "source": {"file": ".../.vqapr/workspace.yaml", "key_path": null, "line": null},
  "cause": {"type": "FileNotFoundError", "message": "[Errno 2] ...",
            "where": "vqapr/workspace.py:1053 (_read)", "origin": "framework",
            "traceback": "Traceback (most recent call last):\n  File ..."}}]}
```

A `KeyError` inside an author's `decide()` renders `status: 502`, `code:
"strategy.callback.intent"`, `cause.origin: "user"`, `cause.where` the author's own file and
line, and the traceback Python would have printed.

## Trade-offs

- **Breaking for every 0.6.0 agent.** All 113 codes, every `stage` value, `family` and
  `explain`. Done now because it is pre-1.0 and because the old shape gave an agent no field to
  branch on for the question it asks first.
- **`status` is a hint, `cause` is the truth.** The owner's rule: the taxonomy is not proven
  MECE, so nothing is withheld. Tracebacks are inline and uncut. The envelope is larger; a reader
  who wants the short form reads `fix`.
- **`check` folds stages.** Its envelope reports one `stage: "check"` over failures collected
  from opening, lookup and freezing; the per-failure stage is not carried on the entry. Adding it
  would be one more key, and no consumer has asked for it.
- **`strategy.*` codes are not enumerated statically.** They are a re-render of
  `SimulationStage`, so the baseline lists them under `by_cause` only by shape. The scanner could
  enumerate the enum; not done until something reads that list.
- **`judgment.blocked` inherits the blocking refusal's status** rather than always 500/502 by
  frame. A judge blocked by `component.unregistered` is the user's 404, and rendering it 500
  would send them upstream for their own typo.
- Two sites' names were changed after migration on review: `run.reference_unregistered` →
  `run.unregistered` at stage `lookup` (it is `Workspace.run_definition`, a lookup, the sibling
  of `dataset.unregistered`).

## Validation

On the tree at the second commit of this record, 2026-09-08, alone on the machine:

- `uv run ruff check src/`: clean. `uv run vulture`: no output.
- `python -m tests.characterization.refusal_codes` regenerated the baseline once, after every
  raise site was migrated: `unresolved: []`.
- `uv run pytest tests/ -q` (iteration check): 1318 passed, 24 deselected; the one failure it
  found was a stale regex on the old `workspace.remove.*` codes, fixed.
- `test_all` (`uv run pytest tests/ -q -m ""`): **1476 passed in 396.7 s**, all eight showcases
  included (the count rose from 1453 by the new status, cause and envelope tests). The slowest
  five are the showcase block (59.6 s setup), the sample panel build (52.9 s), and three
  sample-driven runs; the same shape record `169` measured.
- A real envelope, `vqapr check nothing` in an empty directory, is quoted above: `status: 404`,
  `cause.where: vqapr/workspace.py:1053 (_read)`, the `FileNotFoundError` traceback whole.
