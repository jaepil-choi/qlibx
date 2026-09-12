"""Record `256`: a run with a record keeps what its fills produced in the record, not in memory.

`docs/issues/report-2026-09-11-a-strategy-runs-memory-grows-with-its-orders-far-past-the-
documented-per-worker-size.md`. A daily 309-name book grew about 6 KB of private memory per fill.
Measured on a synthetic 300-name run, about 1.4 KB of it was one object graph -- each fill's
commit, mark and feedback evidence -- held three times over: on the roots' lifecycle entries, in
`feedback`, and in the market clock's traces. Removing any one or two frees nothing; a stored run
now holds none of the three, because its fills are `vqapr.fill` rows the moment they are made
(the rule record `221` set for rows). What the strategy DECIDED stays, because `callback_evidence`
is how an in-process caller reads it (showcases 006-008 do). A run without a record keeps
everything, as before.

The shipped sample journey: one strategy over the sample panel, with fills.
"""

from __future__ import annotations

import gc
from pathlib import Path

import tests.sample.journey as journey
from vqapr.public import (
    StrategyEntry,
    Workspace,
    freeze,
    register_run,
    register_strategy_model,
)
from vqapr.public import run as execute_run
from vqapr.run.engine.context import (
    DueExecutionResult,
    HeldResult,
    InstantOutcome,
    SimulationResult,
    callback_evidence,
)
from vqapr.run.engine.evidence import CallbackEvidence, DueExecutionEvidence
from vqapr.run.engine.loop import DueExecutionTrace
from vqapr.run.engine.run_state import LifecycleKind

_DECISIONS = {LifecycleKind.NO_DECISION, LifecycleKind.ACCEPTED_INTENT}


def _run(tmp_path: Path, *, store: Path | None) -> SimulationResult:
    project = tmp_path / "project"
    project.mkdir()
    panel = journey.install(project)
    register_strategy_model(project, "reversal", journey.STRATEGY_SOURCE, "SampleReversal5d")
    register_run(
        project,
        journey.definition(panel, run_id="kept").replace(
            strategy=StrategyEntry("reversal"), writes="kept-weights"
        ),
    )
    frozen = freeze(project, Workspace.open(project).run_definition("kept"))
    return execute_run(project, frozen, store_root=store).result("reversal")


def test_a_run_with_a_record_keeps_its_decisions_and_not_its_fills_evidence(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, store=tmp_path / "store")
    gc.collect()

    fill_side = [e for e in result.final_state.lifecycle_trace if e.kind not in _DECISIONS]
    assert fill_side, "the sample run commits and marks"
    assert all(entry.detail is None for entry in fill_side), "kinds, not evidence"
    assert result.final_state.feedback == ()
    market = [trace for trace in result.events if isinstance(trace, DueExecutionTrace)]
    assert market and all(isinstance(trace.result, InstantOutcome) for trace in market)
    assert not any(isinstance(item, DueExecutionEvidence) for item in gc.get_objects()), (
        "no fill's evidence survives the run that recorded it"
    )

    decisions = callback_evidence(result)
    assert decisions and all(isinstance(entry, CallbackEvidence) for entry in decisions), (
        "what the strategy decided stays readable in-process"
    )


def test_a_run_without_a_record_keeps_everything(tmp_path: Path) -> None:
    result = _run(tmp_path, store=None)

    assert result.final_state.feedback, "an in-memory run keeps each fill's evidence"
    assert all(
        entry.detail is not None
        for entry in result.final_state.lifecycle_trace
        if entry.kind is LifecycleKind.ACCOUNT_COMMITTED
    )
    market = [trace for trace in result.events if isinstance(trace, DueExecutionTrace)]
    assert market and all(
        isinstance(trace.result, DueExecutionResult | HeldResult) for trace in market
    )
