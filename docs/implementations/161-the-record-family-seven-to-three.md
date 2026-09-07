# 161 — the record family, 7 → 3: one field set per record, the frozen run in its own file

**Closes:** no issue. **Branch:** `step-06-record-family`, off `develop @ 6c6de253`.
**Campaign:** `docs/refactoring/2026-09-04-the-one-shape-campaign.md`, Step 6 (§1.3, last row);
ExecPlan section M6 in `.agent/plans/active/one-shape-campaign.md`. **Authority:** the owner,
2026-09-04 (D1·D2) and 2026-09-07 (Step 5's deferral of `Frozen*`, closed here).

## Why this exists

The record family was seven files and one field list written three times: a tuple per record kind
in `run_records.py`, a lambda-builder dict per kind in `records.py`, and every reader's
`record.get(field)`. `vqapr.fill` was spelled in three places. `model_state.py` was 44 lines with
three importers; `reporting.py` was 36 lines that re-listed the package's own tables. The `Frozen*`
classes shared `run.py` with the declaration they are frozen *from*. Step 6 keeps one of each.

Measured before starting (ExecPlan M6): 3,665 lines in the family; cycles measured *before* anything
moved, because the campaign's target cycle turned out to be stale (below).

## What changed, by milestone

### 6d — the cycle was already gone

Campaign §1.3 lists `valuation ↔ callback` as one of four cycles at `dd55822b`; the handoff points at
`valuation.py:46`. That line is `from vqapr.flow.callback import CallbackPhase` **under
`if TYPE_CHECKING:`** — a type-only import, no runtime edge. Measured with a Tarjan pass over runtime
imports (`TYPE_CHECKING` blocks excluded): **three cycles**, none of them this one —
`data.store ↔ data.windows`, `exchange.conventions ↔ exchange.execution_table`, `cli ↔ cli.main`.
That is Step 7's "남은 순환 셋", now an exact list. This milestone is a measurement.

### 6c — the folds, one of them not where the handoff said

- `model_state.py` → `run_state.py` (`PreparedModelState`, `prepare_model_state`). Two importers
  used the module *as an object* (`import vqapr.flow.model_state as model_state`,
  `monkeypatch.setattr(model_state_module, ...)`), which a grep for `from … import` misses;
  `pytest --collect-only` caught both, as the Step 4 trap said it would.
- `reporting.py` is gone — but **not into `cli/run.py`** as the handoff proposed: `flow/*` importing
  from `cli/` is the inversion record `113` paid for. `FILL_TABLE` lives once, in `run_state.py`
  (`run_state._FILL_TABLE` was the third spelling); `context.DEFAULT_TABLES` builds the fill spec
  from it; `FRAMEWORK_TABLES` is derived from `DEFAULT_TABLES` in `context.py` rather than listed
  again; `recorded()` had no source consumer and its one test inlines the attribute.

### 6b-1 — three record models own the field set

`RunRecord`, `StrategyRecord`, `DatamodelRecord` (pydantic, `extra="forbid"`, every field required)
in what is now `flow/record.py`. The freeze functions construct them — a field missing or unknown is
refused at construction, before anything reaches disk — and `RunRecordWriter.finish`/`write_run_record`
accept a model or a mapping and dump through the existing `_encode`, so the JSON on disk did not
move (`test_run_freezes_its_record.py` pins every field of `run.json`; 65 record tests passed).
`_STRATEGY_FIELDS`, `_DATAMODEL_FIELDS`, `RUN_JSON_FIELDS` derive from `model_fields`.
`_RUN_FIELDS` stays as written: it is the field set of `record.json`, the pre-139 per-run record
that **no source path writes any more** and `read_record` still reads.

**Readers keep their dict shape, on purpose.** A `strategy.json` written under the same schema
string before `timing` existed must still read; validating reads would break a compatibility the
schema string already governs. The model is the writer's contract about *which answers exist*;
`_encode` fixes how each is spelled.

### 6b-2 — the file reshape

- `flow/record.py` = `run_records.py` + `records.py` (merge checked cycle-safe first: none of
  `simulation`, `datamodel`, `run_state`, `loop` import `run_records`).
- `flow/frozen.py` = the `Frozen*` half of `run.py` (from `class FrozenAgenda` down), importing the
  twelve shared helpers from `run.py`; the split was verified by AST to leave no `run → frozen`
  reference. `run.py` is the declaration; `frozen.py` is what preflight makes of it.
- `DatasetDocument`/`ExecutionInputDocument`/`FillDocument` → `*Codec`, the name Step 5's judgment
  gave them.
- Re-pointed by AST/sed: 12 files (`Frozen*` → `flow.frozen`), 29 files (`records`/`run_records` →
  `flow.record`). Three references the rewriters could not see were fixed by hand: a module *path*
  in `test_internal_holds_no_extension_authority.py`'s allow-list, a function-local
  `from vqapr.flow.run import FrozenStrategy` in `test_public.py`, and a comment naming the old file.

### 6a — not needed, and recorded rather than done

Step 5 deferred "`Frozen*` → pydantic" to here on the condition that Step 6's record models would
need to `model_dump` a frozen object. They do not: every record field is *derived* (`period`,
`exchange` as a dict, `contract_report(result)`, `timing`), and identities are hashed from explicit
payloads. `Frozen*` are neither declared nor on disk as themselves, so D1 does not reach them. They
stay dataclasses, in their own file, with the reason in that file's docstring.

## Corrections to the plan of record

1. §1.3's `valuation ↔ callback` cycle did not exist at the start of this step (6d).
2. The handoff's "`reporting` → `cli/run`" would invert the layers (6c).
3. Record `160` said `_require_id` was deleted in Step 5; it was not — the `Frozen*` use it.
   Corrected in that record.
4. Every Step 5/6 event was dated `2026-09-05` -- the handoff and campaign rows, record `160`'s
   header, the ExecPlan's "opened"/"measured" lines. The reflog says `step-05` was created
   2026-09-07 07:37 and `step-06` at 09:44; the session that did both began on the 5th and
   kept its first date. All of them now say the 7th; Step 4 (merged the 5th) stands.

## Measured

| | after Step 5 (`6c6de253`) | after Step 6 |
|---|---|---|
| modules under `src/vqapr` | 125 | **123** |
| lines under `src/vqapr` | 31,766 | 31,761 |
| the record family | 7 files, 3,665 lines | **3 files** (`frozen.py` 490 · `record.py` 1,806 · `run_state.py` 760), 3,056 lines, beside `run.py` 604 |
| field lists per record kind | 3 (tuple, builders, readers) | **1** (the model; tuples derived) |
| spellings of `vqapr.fill` | 3 | **1** |
| runtime import cycles | 3 | 3 (the same three; Step 7's list) |

## Validation

Collection after each milestone (`pytest --collect-only -q`): 1425 → 1425 → 1425 → 1425 → 1425
(record 160 closed at 1425; nothing added, one `recorded()` test folded into its neighbour). The
Step 4 trap was run on purpose after every deletion: `--collect-only` caught the two module-as-object
importers of `model_state` and the three hand-fixed references in 6b-2 before any suite ran.

Targeted, per milestone: 6c `tests/flow` + `tests/cli` (the `FILL_TABLE`/`FRAMEWORK_TABLES` readers);
6b-1 the 65 record tests (`test_run_freezes_its_record.py`, `test_the_record_reads_back_typed.py`,
`test_a_missing_record_is_refused_by_name.py`, `tests/flow/test_run_records*.py`); 6b-2 `tests/flow`,
`tests/boundaries` (the deferred-import ratchet holds at its exact ceiling), `tests/characterization`
(the refusal-code baseline is unchanged: no refusal was added or renamed).

Full suite, showcase gate included: **1425 passed, 0 failed, 11,764 warnings in 1110.33 s** (the
documented race flake, `test_five_processes_racing_...`, did not fire this run). The wall time is
longer than Step 5's 800 s because the run shared the machine with the owner's licensing work.

Lint: `uv run ruff check src/` (the declared gate) is clean. Over `src tests showcases`, develop had
41 findings and this branch has 32 -- nine `SIM117`s left with Step 5's nested `with` blocks; no
finding is new, and every remaining one is a pre-existing `E501` in `tests/` or `showcases/`.
`ruff format` is not a gate (develop has 120 unformatted files) and was not applied.
