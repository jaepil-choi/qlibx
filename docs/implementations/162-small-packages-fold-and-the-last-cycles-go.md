# 162 — small packages fold, and the last three import cycles go

**Closes:** no issue; closes the one-shape campaign's last step. **Branch:** `step-07-fold-packages`,
off `develop @ 23811611`. **Campaign:** `docs/refactoring/2026-09-04-the-one-shape-campaign.md`,
Step 7 (§2, row 7); ExecPlan section M7 in `.agent/plans/active/one-shape-campaign.md`.
**Authority:** the owner, 2026-09-04 (the campaign) and 2026-09-07 ("계속 작업해서 완료하고 안전하게
버전을 올린 뒤" — finish Step 7, then release, then tell the testbeds).

## Why this exists

Four packages were smaller than their directory: `domain/` was ten modules averaging 120 lines,
`constraints/` carried a 22-line re-export and a findings file beside the evaluation that stamps
them, `valuation/` was two modules read almost only by `flow/`, and `runtime/` was two modules
whose one non-`flow` importer was `calls.py`. Three import cycles remained, each hidden behind a
function-local import that the ratchet (record `126`) counts but cannot see through. Step 7 folds
the four and cuts the three.

The campaign row gives counts (`domain/` 10→4, `constraints/` 7→3), not module names. The names
were chosen from measurement, and two of the counts were wrong for reasons the row could not see;
both are recorded below rather than forced.

## What changed, by milestone

### 7a — the cycles, first, before any file moved

- **`cli ↔ cli.main`.** The entry point `vqapr.cli:main` and `__main__.py` went through
  `cli/__init__`, which imported `main`, which imports every command *through the package*. The
  entry point is `vqapr.cli.main:main` now (`pyproject`, `__main__`, two tests); `cli/__init__.py`
  imports nothing.
- **`data.store ↔ data.windows`.** `store.py` deferred `AccessRecord`/`ObservationBatch` behind
  `_window_types()` because `windows.py` imported the store. The two are the shapes the store
  *produces*, so they live in `store.py`; `windows.py` imports them from there; `public` re-exports
  unchanged.
- **`exchange.conventions ↔ exchange.execution_table`.** `FillConvention.build_horizon` and
  `select_target` took the registration and `isinstance`-checked it through a deferred import; the
  convention is the lower layer and must not know the registration. They take what they read —
  `source: SourceSpec`, `trade_at_field`, and (for the target's identity, which the first cut missed
  and ruff caught) `execution_input_id` — and `ExecutionInputRegistration.build_horizon`/
  `select_target` pass their own. Three source callers and eleven test sites say
  `execution_input.select_target(...)`.
- Runtime cycles (Tarjan over module-level and function-local imports, `TYPE_CHECKING` excluded):
  **3 → 0**. Deferred-import ratchet **18 → 15**, lowered in the same commit.

### 7b — `domain/` 10 → 4 (then 5)

`references` → `identifiers` (a `ModelStateRef` is a name). `roster` + `roster_export` →
`instruments` (what an id is, the declared roster of them, and the roster's on-disk spelling;
`roster_export` is pure — no pyarrow — so nothing heavy entered the layer). `timestamps` + `rows` +
`memory` + `enums` → **`values.py`**, the portable values every layer shares. Names did not change;
54 importers were re-pointed by dotted path, and each folded module's docstring survives as a
comment section above its code. Ratchet **15 → 13**: `cli/list_.py` and `declarations.py` each
deferred `build_roster` and `read_roster_table` from two modules; after the fold they are one
statement each. The deferrals stayed; the count is statements, and the note beside `CEILING` says so.

### 7c — `constraints/` 7 → 5, not 3

`constraint.py` re-exported `vqapr.authoring`'s `Constraint` family "so internal paths name the layer
they belong to". That is a second door to one definition (D2), so it is deleted and its 17 importers
— `evaluation`, `extension/loading`, `flow/context`/`preflight`/`simulation`, `public`,
`testing/conformance`, ten tests and three generated-source strings — name `vqapr.authoring`. One
refusal's `fix` sentence named the old path and now names the real one. `findings.py` folds into
`evaluation.py` (the findings and the evaluation that stamps them). **`builtin/` stays a directory of
two files**: a shipped constraint is registered by its own path (`shipped_constraint_path` resolves
`builtin/<name>.py`), and "a component is a file" (record `160`, decision A) forbids merging them.
The row said 3; the path rule allows 5.

### 7d — `valuation/` → `flow/marking.py` (a sibling) and `domain/values.py`

The row says `flow/valuation` **옆** — *beside* — and beside is exactly right: `flow/context.py`
imports `marking` and `flow/valuation.py` imports `context`, so folding `ValuationService` *into*
`valuation.py` would have created a cycle in the step that removes cycles. `marking.py` moved to
`flow/marking.py`. `Mark`/`MarkBatch` are values imported by `account/` and `constraints/` — below
`flow/` — so they joined `domain/values.py` rather than moving up.

### 7e — `runtime/` → `domain/agendas.py` and `flow/loop.py`

`calls.py` — the call shapes a Model is handed — imports `OperationOccurrence`. `flow/agendas.py`
would have made the authoring layer import `flow/`; an occurrence is a value, so `agendas.py` is in
`domain/` (which is why `domain/` closes at **5** modules, not the row's 4). `events.py`'s two
envelopes fold into `flow/loop.py`, their consumer, which imports nothing else from `flow/` —
`context` would have dragged the dispatch loop up to the whole run context. Two tests moved with
their subjects (`tests/runtime/*` → `tests/domain/`, `tests/valuation/*` → `tests/flow/`);
`tests/boundaries/test_runtime.py` ("runtime does not import data") became
`test_domain_imports_only_itself.py`, the general guard: every module under `domain/` imports
`vqapr.domain.*` and the standard library, nothing else. `vqapr.runtime` left the capability-absence
list with a comment saying where its halves went.

## Found on the way

The first full run failed 11 tests in `test_every_new_kind_says_how_to_use_its_file.py`, none of
them about Step 7: the same test fails on a `develop` worktree. `vqapr` writes its envelope as
UTF-8 bytes on purpose (`cli/main.py`, so an em dash survives a cp949 console), and the test spawned
`python -m vqapr` with `text=True` and no encoding, so the parent decoded that UTF-8 with the
locale. It only shows when the tmp path carries a non-ASCII character (the owner's user name), and
Step 6's run had inherited a UTF-8 setting from the shell. The four `subprocess.run` calls that spawn
the CLI in two test files now say `encoding="utf-8"`, which is the contract the CLI already keeps.

## Corrections to the plan of record

1. `domain/` closes at 5, `constraints/` at 5 — for the reasons in 7c and 7e, each a rule the
   campaign row did not know about (a shipped file's path; an authoring-side importer).
2. `valuation/` → `flow/valuation` **옆**, not into it: the fold would have been a cycle.
3. `runtime/` did not go to `flow/` whole: `agendas` is a value.
4. Handoff §3's "Step 7 — 캠페인 §2 표 그대로. 마지막에." is now the record above.

## Measured

| | after Step 6 (`23811611`) | after Step 7 |
|---|---|---|
| modules under `src/vqapr` | 123 | **111** |
| lines under `src/vqapr` | 31,761 | 31,757 |
| `domain/` | 11 files, 1,215 lines | **6 files**, 1,593 lines (`agendas` and `marks` joined) |
| `constraints/` | 7 files, 757 lines | **5 files**, 726 lines |
| `valuation/` · `runtime/` | 3 + 3 files | **gone** (`flow/marking.py` +1; `flow/` 16 → 17) |
| runtime import cycles | 3 | **0** |
| deferred-import ratchet | 18 | **13** |
| files changed vs develop | — | 100 (+1,122 / -1,102) |

The line count is flat: what left was directories, `__init__`s, a re-export, two deferral helpers
and seven import blocks, and what arrived was section comments carrying the folded docstrings.

## Validation

Collection after every deletion (`pytest --collect-only -q`): 1425 → 1425 → 1425 → 1425 → 1425.
Targeted, per milestone, all green: 7a `boundaries`+`exchange`+`data`+`cli` (113) then `flow` (394);
7b `domain`/`exchange`/`data`/`flow`/`runtime`/`orders`/`extension`/`boundaries`/`constraints` (574);
7c `constraints`/`flow`/`boundaries`/`extension`/`characterization` (394 — the refusal-code baseline
is unchanged); 7d+7e `domain`/`flow`/`boundaries`/`analysis`/`constraints`/`orders`/`exchange`/
`portfolio` (476). The ratchet test was run after each of 7a and 7b and lowered in the same commit.

Full suite, showcase gate included, twice. **First run: 1414 passed, 11 failed** — the encoding
fault above, not Step 7 (the same test fails on a `develop` worktree). **Second run, after the
test fix: 1423 passed, 2 failed**, both concurrency tests and both green in isolation:

- `test_a_process_killed_mid_write_leaves_rows_and_no_record` kills its worker on a timer; when the
  process starts slowly the kill lands before the first parquet part exists. Looped six times on this
  branch it failed once; on a `develop` worktree it failed on the first run. Pre-existing, added to
  the handoff's flake note beside `test_five_processes_racing_...`.
- `test_parallel_registrations_all_survive` passed 14 of 14 in isolation and failed once under the
  full suite's load. Not reproduced; recorded, not explained.

Lint: `uv run ruff check src/` clean at every milestone; the test-side count is the same 32
pre-existing `E501`/`B017` findings as before Step 7. `ruff format` is not a gate and was not applied
(one accidental run on five test files was reverted before commit).
