"""One run's refusal is that run's outcome, and a worker's refusal comes back.

`docs/issues/archive/073`: under `--jobs` a strategy's `SimulationFailure` could not be pickled
back to the parent (its keyword-only constructor and the `Rebalance` it kept on itself), so the
batch ended `stage: unhandled` with `failures: []` and named none of the strategies that had
finished. `docs/issues/archive/071`: the failure named no strategy and its `source` was three
nulls.

**The unit moved on 2026-09-09** (`docs/design/two-clocks-and-the-wiring-table.md` §2.3). A run
holds one model, so what used to be three strategies in one run is three runs, and the guarantee
this file pins moved with them: one refusal is reported as that RUN's outcome and the others
still run. The pickling rule is unchanged -- it is why the worker returns a `StrategyOutcome`.

Three runs of the shipped sample journey: the sample strategy twice, and a strategy that raises
from its own file between them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import tests.sample.journey as journey
from vqapr.flow.engine.artifacts import SimulationFailure
from vqapr.flow.orchestration import in_workers, run_registered_strategy
from vqapr.public import (
    StrategyEntry,
    StrategyOutcome,
    Workspace,
    preflight_run,
    register_run,
    register_strategy_model,
)
from vqapr.public import run as execute_run
from vqapr.record import read_run_record, strategy_refs

RAISING_SOURCE = '''"""A strategy whose signal is never ready; it raises from a helper in this file."""

from vqapr.authoring import DatasetInput, RowsLookback, StrategyModel


def not_ready(names: int) -> None:
    raise ValueError(f"the signal is not ready: {names} names, 5 needed")


class NeverReady(StrategyModel):
    def inputs(self):
        return {
            "prices": DatasetInput(
                dataset_id="sample-prices", fields=("close",), lookback=RowsLookback(rows=2)
            )
        }

    def decide(self, call):
        window = call.read("prices", "close")
        not_ready(len(window.instruments))
'''
RAISE_LINE = RAISING_SOURCE.splitlines().index(
    '    raise ValueError(f"the signal is not ready: {names} names, 5 needed")'
) + 1
"""The line of the author's file the failure must point at: the raise inside the helper, not the
call in `decide()` and not the Flow's guard."""

STRATEGIES = ("ou-first", "never-ready", "ou-last")


def _project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    project.mkdir()
    panel = journey.install(project)
    raising = tmp_path / "never_ready.py"
    raising.write_text(RAISING_SOURCE, encoding="utf-8")
    register_strategy_model(project, "ou-first", journey.STRATEGY_SOURCE, "SampleReversal5d")
    register_strategy_model(project, "never-ready", raising, "NeverReady")
    register_strategy_model(project, "ou-last", journey.STRATEGY_SOURCE, "SampleReversal5d")
    for name in STRATEGIES:
        register_run(
            project,
            # Three runs, three outputs: a run writes a dataset nobody else writes (design §2).
            journey.definition(panel, run_id=name).replace(
                strategy=StrategyEntry(name), writes=f"{name}-weights"
            ),
        )
    return project, tmp_path / "store"


def _assert_failure_names_its_strategy(failure: dict) -> None:
    """The payload alone says which strategy, which file and which line (`071`)."""
    assert failure["component_id"] == "never-ready"
    (entry,) = failure["failures"]
    assert entry["code"] == "strategy.callback.intent"
    # 502, not 500: the innermost frame of the traceback is the author's file, so the author's
    # code crashed and the framework is only the gateway that ran it (record `171`).
    assert entry["status"] == 502, entry
    assert entry["cause"]["type"] == "ValueError"
    assert entry["cause"]["origin"] == "user"
    assert entry["cause"]["traceback"].startswith("Traceback"), entry["cause"]
    assert "never_ready.py" in entry["cause"]["traceback"]
    assert entry["observed"].startswith("the signal is not ready: "), entry["observed"]
    assert entry["source"]["key_path"] == "strategies.never-ready"
    assert entry["source"]["file"].endswith("never_ready.py"), entry["source"]
    assert entry["source"]["line"] == RAISE_LINE, (
        "source must point at the raise in the author's file, not at the Flow's guard"
    )


def test_one_runs_refusal_is_its_outcome_and_the_other_runs_still_run(tmp_path: Path) -> None:
    project, store = _project(tmp_path)
    statuses: dict[str, str] = {}
    for name in STRATEGIES:
        frozen = preflight_run(project, Workspace.open(project).run_definition(name))
        outcome = execute_run(project, frozen, store_root=store)
        statuses[name] = "completed" if outcome.ok else "failed"

    assert statuses == {
        "ou-first": "completed",
        "never-ready": "failed",
        "ou-last": "completed",
    }, "the run after the refused one ran; nothing about the refusal reached it"
    assert len(strategy_refs(store, "ou-first")) == 1
    assert len(strategy_refs(store, "ou-last")) == 1
    assert strategy_refs(store, "never-ready") == (), "the refused run left no record"

    frozen = preflight_run(project, Workspace.open(project).run_definition("never-ready"))
    refused = execute_run(project, frozen, store_root=store)
    failed = refused.errors["never-ready"]
    assert isinstance(failed, SimulationFailure)
    assert failed.component_id == "never-ready"
    assert "[never-ready]" in str(failed), "the human form names the strategy too"
    _assert_failure_names_its_strategy(failed.as_dict())
    assert refused.outcomes["never-ready"].failure == failed.as_dict()

    # A Python caller asking for the refused run's result meets the real exception.
    with pytest.raises(SimulationFailure):
        refused.result("never-ready")


@pytest.mark.slow
def test_a_workers_refusal_comes_back_as_its_outcome_under_jobs(tmp_path: Path) -> None:
    """The finding itself: `--jobs`, one refusal, the parent used to see `cannot pickle`.

    The pool spreads RUNS now, so this is three runs in three processes rather than three
    strategies of one -- the pickling rule it pins is the same.
    """
    project, store = _project(tmp_path)

    outcomes: dict[str, StrategyOutcome] = in_workers(
        list(STRATEGIES),
        run_registered_strategy,
        (False, True),
        jobs=3,
        store=store,
        root_path=project,
    )

    assert {name: o.status for name, o in outcomes.items()} == {
        "ou-first": "completed",
        "never-ready": "failed",
        "ou-last": "completed",
    }
    failed = outcomes["never-ready"]
    assert failed.record is None and failed.error is not None
    assert "SimulationFailure" in failed.error and "cannot pickle" not in failed.error
    _assert_failure_names_its_strategy(dict(failed.failure))
    assert len(strategy_refs(store, "ou-first")) == 1
    assert strategy_refs(store, "never-ready") == ()
    # Every run of the batch has the record a single run has (record `249`).
    for name in STRATEGIES:
        assert read_run_record(store, name)["strategies"][0]["component_id"] == name


def test_a_batch_worker_writes_the_run_record_a_single_run_writes(tmp_path: Path) -> None:
    """`docs/issues/report-2026-09-11-a-jobs-batch-writes-no-run-record-...`.

    The `--jobs` worker called the strategy member directly, and `run.json` was written only by
    `run` before it called in -- so a batch reported every run completed, `list runs` listed them,
    and `show run` refused each one as unknown. The worker is called in this process here, which
    is the whole path a pool worker takes minus the pickling (record `249`).
    """
    project, store = _project(tmp_path)

    outcome = run_registered_strategy(str(project), "ou-first", str(store), False, True)

    assert outcome.status == "completed"
    run_json = read_run_record(store, "ou-first")
    assert run_json["strategies"] == [
        {"component_id": "ou-first", "record": str(outcome.record["strategy_ref"])}
    ]
    assert run_json["writes"] == "ou-first-weights"
