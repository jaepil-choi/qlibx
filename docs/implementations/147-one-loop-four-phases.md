# 147 — one loop, four phases

**Closes:** nothing in `docs/issues/` by number. **Step:** 6 of
`docs/refactoring/2026-09-03-the-deletion-campaign.md` (C-2), the diagnosis's S3 for
`flow/simulation.py` and the structural review's Step 5, both deferred by two campaigns until
the flow had stopped being rewritten (records `118`, `135`, `139`, `146`).
**Authority:** architecture §1.2 (*"flow는 경제 규칙을 소유하지 않는다"* -- a layer that owns no
rules cannot be 2,200 lines); campaign Step 6's table of cut lines, chosen so that Step 7's
DataModel flow is "the loop and the callback phase, without execution and valuation".

## Why this exists

`SimulationFlow` was 2,202 lines and 55 methods in one class: the occurrence loop, the failure
envelope, the callback (restore the model's state, read the window, `decide`, stamp and check
the intent, record, publish), the due execution (snapshot, `plan_orders`, `execute`,
`prepare_fill`, commit, mark), and valuation and monitoring. The method names already fell into
those four groups; the class did not. Every reader of one phase read the other three, and the
next step -- a DataModel that runs as a strategy without an account or a venue -- had no seam
to be defined at.

## What changed

Mechanical. Every method moved verbatim to the module of its phase; what changed inside a body
is the spelling of a reference, retargeted by regex, and nothing else. The spine (`optimize`,
`plan_orders`, `Account.prepare_fill`, `Fill.__post_init__`) is called from the execution phase
exactly as it was called from the class.

| module | holds | lines |
|---|---|---|
| `flow/simulation.py` | `SimulationFlow`: `__init__` (validation, then the context and the three phases), `run` (the loop), `_pending_due`, `_dispatch_due`; re-exports of every name a caller imported from it before | 301 |
| `flow/context.py` | the value classes every phase produces or consumes (`AcceptedIntent`, `PendingValuation`, the traces and results, `FailedAfterCommit`), `DEFAULT_TABLES`, the package-table guard, and `FlowContext`: the run's shared state (frozen run, layer, run state, account, venue, strategy, constraints, valuation service, scan session, roster, reference price, the two window factories, the mark memo, the horizon cache) and the failure envelope (`guard`, `failure`, `due_boundary`) | 468 |
| `flow/callback.py` | `CallbackPhase.dispatch` and its twenty-four helpers: the visible model state, the windows, `decide`, stamping and authority, the package's own rows, evidence, publication, and accepting an intent or a valuation into the horizon | 788 |
| `flow/execution.py` | `ExecutionPhase.execute_due`: snapshot, orders, fills, the account commit, then the mark at the same instant through the valuation phase; `bind_registry_to_venue`; the one-clock stamp (`058`) | 380 |
| `flow/valuation.py` | `ValuationPhase`: `value_due` (a `Hold` reaching its execution instant), `dispatch_valuation` (a standalone valuation occurrence), `dispatch_monitoring` (+ record `140`'s findings table), the committed-mark readers, `_marks_from_execution_snapshot` | 518 |

- **`FlowContext`** is the one object the phases share; a phase holds it and, where it calls
  another phase, that phase (`callback -> valuation.committed_mark`, `execution ->
  valuation.publish_marked`, `valuation -> callback.execution_horizon`). Nothing reaches into
  another phase's private state.
- **Entry points are public names** (`dispatch`, `execute_due`, `value_due`,
  `dispatch_valuation`, `dispatch_monitoring`, `load_visible_strategy_state`,
  `execution_horizon`, `bind_registry_to_venue`, `committed_mark`, `publish_marked`); every
  helper keeps its underscore and its docstring.
- **`simulation.py` re-exports** `AcceptedIntent`, `SimulationResult`, `callback_evidence`,
  `DEFAULT_TABLES`, `DEFAULT_TABLE_PREFIX`, the traces and results, and the two private helpers
  tests imported (`_shadows_package_table`, `_marks_from_execution_snapshot`), so no caller
  changed an import. Tests that reached into the class (a monkeypatched module function, a
  private method, a private attribute) now reach into the phase that holds it -- six sites.
- **Docstrings** elsewhere that pointed at `flow/simulation.py::<helper>` point at the phase.

## What this does not do

- No behaviour changes. No method was rewritten; no rule moved out of `flow/` (that the flow
  still holds `_validate_intent_authority`, `_execution_horizon`, `_standalone_marks` is the
  structural review's S3 observation, unchanged and now visible per phase).
- `flow/materialize.py` is untouched; Step 7 replaces its loop with `SimulationFlow` minus the
  execution and valuation phases, which is the seam this record makes.

## Validation

```
uv run ruff check src/                              All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -m "" -rfE      1355 passed, 1 failed -> the refusal-code inventory: one code moved file
                                                    (run.assembly.constraint_identity, simulation.py -> context.py), baseline
                                                    regenerated deliberately; characterization 85 passed
uv run vulture                                      nothing new in src/
```

**The tracer gate.** A PEP 669 `sys.monitoring` trace of the sample journey
(`vqapr.agent.sample.journey`: install, then execute) recording every function start under
`vqapr/flow/`, taken on the branch point (`develop @ 80e1afb5`, a detached worktree) and on this
branch:

| | flow calls |
|---|---:|
| before the split | 155,632 |
| after the split | 155,636 |

With the moved names normalised (class prefix dropped, the entry points' new public names mapped
back), the two sequences are identical in order; the four extra calls are the four new
constructors (`FlowContext`, `ValuationPhase`, `CallbackPhase`, `ExecutionPhase`). Same
functions, same order, which is what "mechanical" claims.

Sizes: `simulation.py` 2,202 -> 301 lines; the four phase and context modules total 2,154. Six
test sites that reached into the class were re-pointed at the phase that holds what they touch.
