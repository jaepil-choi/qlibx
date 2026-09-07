"""A run reports every strategy it was asked to run, and a worker's refusal comes back.

`docs/issues/073`: under `--jobs` a strategy's `SimulationFailure` could not be pickled back to
the parent (its keyword-only constructor and the `Rebalance` it kept on itself), so the run ended
`stage: unhandled` with `failures: []` and named none of the seven strategies that had finished.
In a single process the loop stopped at the first exception and the strategies after it never
ran. `docs/issues/071`: the failure named no strategy and its `source` was three nulls.

The run here is the shipped sample journey with the sample strategy registered twice and a
strategy that raises from its own file between them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import vqapr.agent.sample.journey as journey
from vqapr.evidence.artifacts import SimulationFailure
from vqapr.flow.record import strategy_refs
from vqapr.public import (
    StrategyEntry,
    StrategyOutcome,
    Workspace,
    preflight_run,
    register_run,
    register_strategy_model,
)
from vqapr.public import run as execute_run

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


def _project(tmp_path: Path, sample_panel) -> tuple[Path, Path]:
    project = tmp_path / "project"
    project.mkdir()
    panel = journey.install(project, panel=sample_panel)
    raising = tmp_path / "never_ready.py"
    raising.write_text(RAISING_SOURCE, encoding="utf-8")
    register_strategy_model(project, "ou-first", journey.STRATEGY_SOURCE, "SampleReversal5d")
    register_strategy_model(project, "never-ready", raising, "NeverReady")
    register_strategy_model(project, "ou-last", journey.STRATEGY_SOURCE, "SampleReversal5d")
    definition = journey.definition(panel, run_id='mixed').replace(
                     strategies=tuple(StrategyEntry(name) for name in STRATEGIES),
                 )
    register_run(project, definition)
    return project, tmp_path / "store"


def _assert_failure_names_its_strategy(failure: dict) -> None:
    """The payload alone says which strategy, which file and which line (`071`)."""
    assert failure["component_id"] == "never-ready"
    (entry,) = failure["failures"]
    assert entry["code"] == "simulation.callback.intent.ValueError"
    assert entry["observed"].startswith("the signal is not ready: "), entry["observed"]
    assert entry["source"]["key_path"] == "strategies.never-ready"
    assert entry["source"]["file"].endswith("never_ready.py"), entry["source"]
    assert entry["source"]["line"] == RAISE_LINE, (
        "source must point at the raise in the author's file, not at the Flow's guard"
    )


def test_one_strategys_refusal_is_its_outcome_and_the_others_still_run(
    tmp_path: Path, sample_panel
) -> None:
    project, store = _project(tmp_path, sample_panel)
    frozen = preflight_run(project, Workspace.open(project).run_definition("mixed"))

    outcome = execute_run(project, frozen, store_root=store)

    assert [(name, o.status) for name, o in outcome.outcomes.items()] == [
        ("ou-first", "completed"),
        ("never-ready", "failed"),
        ("ou-last", "completed"),
    ], "the strategy after the failed one ran; it used to never start"
    assert not outcome.ok and outcome.failed == ("never-ready",)
    assert set(outcome.results) == {"ou-first", "ou-last"}
    assert sorted(ref.rsplit("@", 1)[0] for ref in strategy_refs(store, "mixed")) == [
        "ou-first",
        "ou-last",
    ], "two records stand; the failed strategy left none"

    failed = outcome.errors["never-ready"]
    assert isinstance(failed, SimulationFailure)
    assert failed.component_id == "never-ready"
    assert "[never-ready]" in str(failed), "the human form names the strategy too"
    _assert_failure_names_its_strategy(failed.as_dict())
    assert outcome.outcomes["never-ready"].failure == failed.as_dict()

    # A Python caller asking for the failed strategy's result meets the real exception.
    with pytest.raises(SimulationFailure):
        outcome.result("never-ready")
    assert outcome.result("ou-first").final_state.version > 0


@pytest.mark.slow
def test_a_workers_refusal_comes_back_as_its_outcome_under_jobs(
    tmp_path: Path, sample_panel
) -> None:
    """The finding itself: `--jobs`, one refusal, the parent used to see `cannot pickle`."""
    project, store = _project(tmp_path, sample_panel)
    frozen = preflight_run(project, Workspace.open(project).run_definition("mixed"))

    outcome = execute_run(project, frozen, store_root=store, jobs=3)

    assert outcome.results == {} and outcome.errors == {}, (
        "nothing in-process crosses the boundary; the outcome does"
    )
    assert {name: o.status for name, o in outcome.outcomes.items()} == {
        "ou-first": "completed",
        "never-ready": "failed",
        "ou-last": "completed",
    }
    assert set(outcome.records) == {"ou-first", "ou-last"}
    assert len(strategy_refs(store, "mixed")) == 2
    failed: StrategyOutcome = outcome.outcomes["never-ready"]
    assert failed.record is None and failed.error is not None
    assert "SimulationFailure" in failed.error and "cannot pickle" not in failed.error
    _assert_failure_names_its_strategy(dict(failed.failure))
    with pytest.raises(ValueError, match="worker process"):
        outcome.result("never-ready")
