# 094 — A run reports the tables it declared, and the counter says what it counts

**Closes:** `docs/issues/024-a-run-that-declared-a-table-reports-none.md`.
**Branch:** `fix/024-tables-declared-and-counter`. Cut only after `fix/022-fill-envelope` merged,
because the counter half is not explicable until fills carry a clock.

## Decision R1, and why the field stays

The campaign deferred this to whoever read the code first, with a binding constraint: **the envelope
and `show run` must not be left disagreeing a second time.** Settled during `fix/015a` and recorded
in `docs/implementations/087`; implemented here.

The reported defect was `tables_declared: []` for a run that declared `ff3.formation` and wrote 42
rows to it. **The empty list was not wrong about what it measured.** There are two unrelated
declaration surfaces:

| surface | declared where | previously read by |
|---|---|---|
| `store.tables` | the run spec's `store:` section | `tables_declared` |
| `StrategyModel.diagnostics()` | the component itself | nothing, in this envelope |

The journey declared through the second and read the first, so `store.tables` was genuinely empty
and the field answered a question the reader was not asking.

**Decision: keep the field and teach it both surfaces.** Removing it was the alternative and was
rejected — a reader asking *what did this run declare* has nowhere else to look, and `show run`'s
`tables` answers a different question, namely what was **recorded**, which is empty for a table
declared but never formed.

### What this deliberately does not re-open

The comment at the call site refuses to emit a `publishes`-shaped claim: a machine-readable
assertion that a **dataset** exists when `list datasets` shows none. That reasoning is intact and
untouched. Naming a declared diagnostic table is not that claim, and nothing in this change says a
dataset was registered. The distinction is stated in `_tables_declared`'s docstring so a later reader
does not collapse the two and undo it.

## What changed

- **`_tables_declared(store, result)`** in `src/vqapr/cli/run.py` returns the sorted union of
  `store.tables` and the non-framework tables the result recorded. `vqapr.account`, `vqapr.fill` and
  `vqapr.weight` are excluded by `_FRAMEWORK_TABLES`: they are present in every run, and restating
  them would make the field useless for the comparison it exists to serve.
  - Honest limit, stated in the docstring: a table declared on the component but never **formed** is
    invisible here, because the run record holds what was recorded rather than the component's
    declaration list.
- **`formations` → `instants`** in `src/vqapr/public.py`. The counter is
  `len({str(row.get("event_time")) for row in rows})` — distinct instants — and it is applied to
  **every** table, including `vqapr.fill`, where a formation is not a thing that happens.
  "Formation" is portfolio vocabulary that only fits one of the tables it labels, which is why the
  reporter could not construct a reading for it. Three consumers updated: `cli/show.py`'s comment,
  `tests/cli/test_show.py`, `tests/flow/test_run_records.py`.

The rename is a public envelope key change, acceptable at `0.2.0a1`.

## Validation

**Gate:** `test_all` (run assembly) + `tests/cli/test_show.py` + `tests/cli/test_envelope.py`.

| check | result |
|---|---|
| `tests/cli/test_a_run_reports_the_tables_it_declared.py` (new) | 5 passed |
| `test_show.py` + `test_envelope.py` + `test_run_records.py` | 29 passed |
| **full suite, all marks** | **1389 passed, 0 failed**, 535.31s |

**Two suite events worth recording rather than hiding.**

*Baseline drift, again a pure relocation.* `run.check.judgment_blocked` moved `run.py:400 → :440`
because `_tables_declared` was inserted above it. Same code, same file, nothing added or removed —
checked from the diff before regenerating.

*One genuine flake.* A `test_all` run failed
`tests/qa/test_run_records_survive_and_race.py::test_five_processes_racing_the_same_id` with
`RunRecordTaken` — five processes deliberately racing one run id. It passes in isolation (5 passed),
this branch's diff touches neither `run_records.py` nor any locking path, and a full rerun was clean
at 1389 passed. Recorded as a flake under parallel load rather than treated as signal, and **not**
patched to make a suite green.

The merge condition's third clause — *the `vqapr.fill` value is the true instant count, which is
only true because story 10 landed first* — holds by construction: fills carry `event_time` as of
`docs/implementations/093`, so the counter that collapsed to 1 now counts what its expression always
said it counted.
