"""The seam that lets `Project` drive the retained execution/valuation engine.

`SimulationSummary` and `summarize` are exercised against a real `SimulationResult`
built from the Flow's own dataclasses, so a rename of a field this seam reads would
break the test rather than leave it silently green. `Project.simulate` is exercised
for its input guard only: an end-to-end run needs a registered workspace and real
parquet execution data that a unit test cannot assemble, and the caller drives that
separately.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from vqapr._internal.run_bridge import SimulationSummary, summarize
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.exchange.conventions import ExactExecutionTarget, FillSelector
from vqapr.flow.run_state import RunStateRepository
from vqapr.flow.simulation import (
    AcceptedIntent,
    DueExecutionResult,
    DueExecutionTrace,
    OccurrenceTrace,
    SimulationResult,
)
from vqapr.models.strategy_model import NoDecision
from vqapr.portfolio.budgets import Budget, PortfolioDirection
from vqapr.portfolio.intents import EconomicPortfolioIntent
from vqapr.runtime.agendas import OperationOccurrence, OperationRole
from vqapr.runtime.events import DueExecutionEnvelope


def _occurrence(identifier: str, role: OperationRole, at: datetime) -> OperationOccurrence:
    return OperationOccurrence(
        identifier,
        role,
        LocalInstantDeclaration(
            at.date(), at.timetz().replace(tzinfo=None), "Asia/Seoul", 0, "+09:00"
        ),
    )


_BUDGET = Budget(
    PortfolioDirection.LONG_ONLY, Decimal("0"), Decimal("1"), Decimal("0"), Decimal("1")
)


def _accepted_intent(at: datetime, target_at: datetime) -> AcceptedIntent:
    occurrence = _occurrence("callback-1", OperationRole.STRATEGY_CALLBACK, at)
    intent = EconomicPortfolioIntent(
        UUID(int=1), "strategy", (), Decimal("1"), _BUDGET, (), 0, None
    )
    target = ExactExecutionTarget(
        UUID(int=2), "execution", target_at, FillSelector.SAME_DAY, "close"
    )
    return AcceptedIntent(intent, occurrence, occurrence.evaluation_time, target)


def _real_simulation_result() -> SimulationResult:
    """A real `SimulationResult` built from the Flow's own dataclasses.

    Two `OccurrenceTrace` entries (one accepted, one declined) plus one
    `DueExecutionTrace`, so `summarize` has to distinguish all three kinds. The final
    account snapshot is version 2, which `summarize` must surface unchanged.
    """
    at = datetime(2024, 3, 5, 4, tzinfo=UTC)
    target_at = datetime(2024, 3, 5, 15, 30, tzinfo=UTC)
    accepted = _accepted_intent(at, target_at)
    declined_occurrence = _occurrence("callback-2", OperationRole.STRATEGY_CALLBACK, at)
    declined = NoDecision(reason="no signal")

    account = AccountState(snapshot=AccountSnapshot(2, Decimal("1000"), {}))
    repository = RunStateRepository(initial_account=account)
    state = repository.current

    occurrences = (
        OccurrenceTrace(
            _occurrence("callback-1", OperationRole.STRATEGY_CALLBACK, at), accepted, state
        ),
        OccurrenceTrace(declined_occurrence, declined, state),
        DueExecutionTrace(
            DueExecutionEnvelope(target_at, str(accepted.pending_id)),
            DueExecutionResult(
                consumed_pending_id=str(accepted.pending_id),
                account_version=2,
                post_account_result=None,
            ),
            state,
        ),
    )
    return SimulationResult(occurrences, state)


def test_summarize_maps_a_real_simulation_result() -> None:
    """Occurrence and execution counts come from the traces; intents from the lifecycle.

    This fixture builds `OccurrenceTrace` entries directly, so its state carries no
    lifecycle entries. That is exactly why `accepted_intents` is 0 here while the two
    trace-derived counts are non-zero: a hand-built trace tuple is not a substitute for
    the engine's own lifecycle record, and `summarize` deliberately trusts the latter.
    """
    result = _real_simulation_result()
    summary = summarize(result)
    assert summary == SimulationSummary(
        occurrences=3, accepted_intents=0, executions=1, final_account_version=2
    )


def test_summarize_reports_no_account_version_when_no_account_committed() -> None:
    repository = RunStateRepository()
    state = repository.current
    result = SimulationResult((), state)
    summary = summarize(result)
    assert summary.final_account_version is None
    assert summary.occurrences == 0
    assert summary.accepted_intents == 0
    assert summary.executions == 0


def test_simulation_summary_is_immutable() -> None:
    summary = SimulationSummary(
        occurrences=1, accepted_intents=0, executions=0, final_account_version=None
    )
    with pytest.raises(AttributeError):
        summary.occurrences = 2  # type: ignore[misc]


def test_simulation_summary_rejects_a_negative_count() -> None:
    with pytest.raises(ValueError):
        SimulationSummary(
            occurrences=-1, accepted_intents=0, executions=0, final_account_version=None
        )


def test_simulation_summary_rejects_a_non_integer_count() -> None:
    with pytest.raises(TypeError):
        SimulationSummary(
            occurrences=1.5, accepted_intents=0, executions=0, final_account_version=None
        )


def test_project_simulate_refuses_a_non_run_definition_before_any_workspace_work(
    tmp_path: Path,
) -> None:
    import vqapr

    root = tmp_path / "project"
    root.mkdir()
    project = vqapr.open(root)

    with pytest.raises(TypeError, match="RunDefinition"):
        project.simulate(definition={"not": "a RunDefinition"})

    assert not (root / ".vqapr").exists()


def test_importing_run_bridge_does_not_pull_flow_or_workspace() -> None:
    """Proves the lazy imports inside `run_bridge` functions are real, not just written.

    Run in a clean subprocess: this process may already hold `vqapr.flow` and
    `vqapr.workspace` in `sys.modules` from other tests in the same session.
    """
    probe = (
        "import sys\n"
        "import vqapr._internal.run_bridge\n"
        "present = sorted(n for n in ('vqapr.flow', 'vqapr.workspace') if n in sys.modules)\n"
        "print(';'.join(present))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    reached = [name for name in completed.stdout.strip().split(";") if name]
    assert reached == [], f"importing run_bridge reached {reached}"


def test_accepted_intents_come_from_the_lifecycle_trace_not_the_result_field():
    """`OccurrenceTrace.result` is annotated `object` and is not a reliable decision probe.

    A real 40-session run accepted 34 intents and executed 34 times, while an isinstance
    probe against `.result` reported zero. The engine's own lifecycle trace is the
    authoritative record, so that is what `summarize` must count.
    """
    from vqapr.flow.run_state import LifecycleKind

    class _Entry:
        def __init__(self, kind):
            self.kind = kind

    class _State:
        account = None
        lifecycle_trace = (
            _Entry(LifecycleKind.ACCEPTED_INTENT),
            _Entry(LifecycleKind.ACCOUNT_COMMITTED),
            _Entry(LifecycleKind.ACCEPTED_INTENT),
            _Entry(LifecycleKind.MARKED),
            _Entry(LifecycleKind.NO_DECISION),
        )

    class _Result:
        occurrences = ()
        final_state = _State()

    summary = summarize(_Result())
    assert summary.accepted_intents == 2
    assert summary.occurrences == 0
