# 052 — Five of the nine showcases do not run, and nothing in the repository executes them

**Status: OPEN, filed 2026-09-02. Two of the five closed by
[`131-one-datamodel-and-a-dead-half-deleted.md`](../implementations/131-one-datamodel-and-a-dead-half-deleted.md)
as a side effect** -- `show_002` and `show_004` failed because their DataModels declared reads in a
retired shape, and converging the DataModel contract retired the shape everywhere at once. Three
remain (`show_005`, `show_006`, `show_008`), all the `SingleNameCap` constructor case. **The second
half -- a gate that runs them -- is still the finding.** Found while establishing a showcase baseline before the
constraint convergence (`docs/issues/036`, record `130`), by running all nine and comparing against
the branch point — not by a user, and not by any gate.

**Touches:** `showcases/show_002`, `show_004`, `show_005`, `show_006`, `show_008`; the absence of
any command or test that runs them.

## What happens

```
show_001_execution_input_registration      OK
show_002_datamodel_materialization         FAIL
show_003_real_data_long_short              OK
show_004_krx_execution_profile             FAIL
show_005_enhanced_index                    FAIL
show_006_ensemble_netting                  FAIL
show_007_signal_measurement                OK
show_008_alpha_family_ensemble             FAIL
show_009_authoring_contract                OK
```

Measured twice on the same tree — once with a working branch applied and once with it stashed —
and the five failures are identical either way. They are not caused by work in flight.

**Three of them share one cause.** `show_005`, `show_006` and `show_008` construct the shipped cap
without the argument it now requires:

```
TypeError: SingleNameCap.__init__() missing 1 required keyword-only argument: 'benchmark_dataset_id'
```

`docs/implementations/035-a-cost-band-names-a-category.md` and the enhanced-index work made the
benchmark dataset an explicit constructor argument. Three showcases were never updated.

`show_002` and `show_004` failed earlier, at `component.load.requirements_failed` — a `DataModel`
whose declaration no longer completed against the current requirement contract. **Closed by record
`131`**, which made every DataModel declare reads one way.

Record `132` converged StrategyModel and re-ran all nine: the same six complete, and the same
three fail on the same `SingleNameCap` line. The gate half of this issue is still open.

## Why this is the finding rather than five separate ones

**Nothing runs them.** `pytest` does not collect `showcases/`. `.agent/project.yaml` declares
`test`, `test_all`, `lint` and `deadcode`, and none of them touches a showcase. The only mention is
`AGENTS.md`'s rule that showcase work follows a nested `AGENTS.md` — a rule about how to change
them, not a check that they still work.

So a showcase can be broken by an ordinary contract change and stay broken indefinitely, and the
package's own worked examples — the artefacts a reader is most likely to copy — decay silently
between releases. That is the defect. The five individual breakages are its symptoms.

**They are also load-bearing for a claim the campaign makes.** `docs/refactoring/2026-09-02-the-convergence-campaign.md`
lists *"showcase 9개 전부 완주"* as a gate on Steps 1, 5 and 7. That gate cannot be met today and was
not measurable before this file, because nobody had run them.

## What to do

Two halves, and the second is the one that matters.

1. **Repair the five.** Mechanical: three need the benchmark dataset id, two need their model
   declarations brought onto the current contract.
2. **Make a gate run them**, so the next contract change either keeps them working or is told at
   once. The cheapest shape is one slow-marked test that executes each `run.py` and asserts it
   exits clean — the showcases already run standalone, so this is a driver rather than a rewrite.
   `.agent/project.yaml`'s `test_all` is where it belongs, since that is what a handoff must pass.

Until the second half exists, repairing the five buys one release.
