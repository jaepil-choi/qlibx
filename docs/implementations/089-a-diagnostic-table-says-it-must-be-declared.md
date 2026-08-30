# 089 — A diagnostic table says it must be declared

**Closes:** `docs/issues/019-a-diagnostic-table-must-be-declared-and-only-the-refusal-says-so.md`.
**Branch:** `fix/019-declare-diagnostics`.

## Why this change exists

Emitting a small table from `decide()` — how many names landed in each of six Fama-French
portfolios — was refused mid-run with:

```
decide() emitted undeclared diagnostic tables: ['ff3.formation']
```

The refusal named the breach and not the repair, and it arrives *during the simulation*, so the
cost of learning it is a whole run. Two sentences had led the author to expect no declaration was
needed:

- the skill's **"Every run records three tables, plus any the model formed"**, which reads as
  *form one and it is recorded*; and
- `StrategyResult`'s own docstring, which introduces `diagnostics` as a convenience —
  *"`next_state` and `diagnostics` default to the empty case, because most strategies carry no
  cross-callback state and emit no diagnostic tables"* — framing the empty default as saving typing
  rather than as a declaration you must override.

## What changed

Three surfaces, because the gap was in all three.

- **The refusal** (`_validated_diagnostics`, `src/vqapr/_internal/models/agent_first.py`) now names
  `StrategyModel.diagnostics()` as the method that declares a table, **and lists what is currently
  declared**. The second half turns a guess into a comparison: an author who declared
  `ff3.formations` and emitted `ff3.formation` sees both spellings side by side instead of hunting
  their own file for a typo the refusal already knew about. Declaring none reads as `nothing`
  rather than as an empty bracket.
- **The scaffold** (`src/vqapr/extension/scaffold.py`) mentions it, so the rule is visible before a
  run is spent rather than after.
- **The skill** (`SKILL.md`) says **declared and then formed**, and states that emitting an
  undeclared table refuses mid-run.

### The scaffold's forty-line budget is a real contract

The first version of the scaffold comment was five lines of prose with a worked example. It pushed
the emitted strategy from 39 to 45 lines and failed two tests at once —
`test_the_emitted_strategy_fits_in_forty_lines` and the unedited-run journey. That budget is
deliberate: the scaffold was cut from 111 lines to 40, and the ceiling guards against framework
bookkeeping creeping back into authored code. The comment was cut to two lines to fit **inside** the
contract rather than being allowed to stretch it.

### A snippet that did not run

The first draft of that comment showed `va.DiagnosticTable.of("id", ("field",))`, by analogy with
the `.of` constructors elsewhere in `authoring`. **`DiagnosticTable` has no `.of`.** The real form is
`DiagnosticTable(table_id=..., semantic_fields=(...))`, confirmed against `authoring.py:372` and
against seven existing call sites in the suite, and the shipped snippet was corrected and then
executed to prove it constructs. A scaffold comment that does not run is worse than no comment,
because it costs the reader the same run this issue is about.

This is the third instance in this campaign of Principle 5 catching an assumption: a plausible API
shape, taken by analogy rather than read.

## Validation

**Gate:** `test_all` (the scaffold changed) + `tests/cli/test_commands.py` +
`tests/qa/test_new_refuses_without_writing.py` + `tests/characterization/test_explain_topics.py`.

| check | result |
|---|---|
| named gate files + `test_agent_surface.py` | 78 passed |
| `tests/qa/test_a_diagnostic_table_says_it_must_be_declared.py` (new) | 4 passed |
| `test_authoring_contract.py` + `test_scaffold_runs_unedited.py` (slow) | 26 passed |
| **full suite, all marks** | **1368 passed, 0 failed**, 406.07s |

The merge condition is asserted directly: the refusal names `StrategyModel.diagnostics()`, the
scaffold mentions declaring a table, and the skill says declared *and* formed. A fourth test asserts
that **declaring a table actually works** — without it, every other assertion would be satisfied by
a refusal that never accepts anything.
