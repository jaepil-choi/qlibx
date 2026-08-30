# 041 — A shipped fix was verified against a test double the real object does not match

**Status:** **CLOSED 2026-08-31** by `docs/implementations/102-a-run-says-what-its-orders-did.md`.
Both envelope fields now read one helper, and the new test pins its attribute path against the real
types rather than against a stand-in.

**Status when filed:** open. Found 2026-08-31 while wiring `docs/issues/039`'s fill summary into the
same envelope, on `develop`. Not a journey finding: it was found because the new field needed the
same rows the broken one was already claiming to read.
**Touches:** `src/vqapr/cli/run.py` (`_tables_declared`);
`tests/cli/test_a_run_reports_the_tables_it_declared.py`;
`docs/implementations/094-a-run-reports-the-tables-it-declared.md`.

## What shipped

`docs/issues/024` reported `tables_declared: []` for a run that declared `ff3.formation` through
`StrategyModel.diagnostics()` and wrote 42 rows to it. Record `094` fixed it by reading both
declaration surfaces — the run spec's `store.tables`, and the tables the model actually formed:

```python
declared.update(
    table_id
    for table_id in getattr(result, "tables", {})
    if table_id not in _FRAMEWORK_TABLES
)
```

`result` is a `SimulationResult`. **`SimulationResult` has no `tables` attribute.** It is a frozen
dataclass with exactly two fields:

```
fields: ['occurrences', 'final_state']
```

The recorded rows live at `final_state.recorder_rows`, which is where `_freeze_record` — three
functions away in the same file — reads them from. So `getattr(result, "tables", {})` returned `{}`
on every real run, and the second half of 024's fix reported nothing for a week.

## Why the suite did not catch it

`tests/cli/test_a_run_reports_the_tables_it_declared.py` builds its own stand-in:

```python
def _result(*table_ids: str) -> SimpleNamespace:
    """A stand-in carrying only what `_tables_declared` reads: the recorded table ids."""
    return SimpleNamespace(tables={table_id: () for table_id in table_ids})
```

The docstring is exactly right about its intent and exactly wrong about the object. Four assertions
passed, including one whose message reads *"a run that declared and wrote ff3.formation still
reports nothing for it"* — the defect's own words, asserted against a shape the defect could not
occur in.

**The rule this is an instance of:** a double built from the code under test rather than from the
type it will receive proves only that the code is self-consistent. Here the double was written by
reading the accessor, so the accessor's mistake was copied into its own verification.

## Why it is worth a file

The 015-027 campaign closed with the line *"an invariant that lives in a document is an invariant
nobody is checking."* This is the third variant of that family in two weeks, and the first where a
**test existed and still proved nothing**:

| instance | the verification that did not verify |
|---|---|
| `docs/issues/028` | a tripwire in prose, run by hand |
| the materialization refusal (record `097`) | an invariant asserted in a docstring; deleting the code left 1,419 tests green |
| this | a unit test against a double the production object does not match |

The cheap general remedy, applied here: when a helper reads an attribute off a framework object,
**pin the path against the real type in the same file** — one `dataclasses.fields` assertion costs
nothing and fails on the rename or the typo that a hand-built double absorbs.

## Not in scope

Record `094`'s reasoning is unaffected: reporting both declaration surfaces is still right, and the
field still stays. What was wrong was one attribute name and the double that hid it.
