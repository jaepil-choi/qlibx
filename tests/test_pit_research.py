from datetime import UTC, datetime
from pathlib import Path

import pytest

from qlibx import OutcomeStatus, QlibxProject, StrategyInvocation
from qlibx.data import AvailableAtField, ComponentRequirement, DatasetRegistration, SourceFormat
from qlibx.kernel import BacktestClock
from qlibx.operations import BudgetMode, StrategyDraft, WeightEntry


def project_with_market(tmp_path: Path) -> tuple[QlibxProject, Path]:
    QlibxProject.init(tmp_path, apply=True)
    source = tmp_path / "market.csv"
    source.write_text(
        "AVAILABLE,CODE,VALUE\n"
        "2025-01-02T08:00:00Z,A,1.0\n"
        "2025-01-02T08:00:00Z,B,3.0\n"
        "2025-01-02T15:30:00Z,A,2.0\n",
        encoding="utf-8",
    )
    current = QlibxProject.open(tmp_path)
    outcome = current.register_dataset(
        DatasetRegistration(
            dataset_id="market",
            source="market.csv",
            source_format=SourceFormat.CSV,
            instrument_field="CODE",
            available_at=AvailableAtField(field="AVAILABLE"),
            logical_key=("AVAILABLE", "CODE"),
            semantic_bindings={"value": "VALUE"},
            source_provenance="PIT fixture",
        )
    )
    assert outcome.status is OutcomeStatus.COMPLETE
    return current, source


class NormalizedValueStrategy:
    strategy_id = "tests.normalized_value"

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return (
            ComponentRequirement(requirement_id="strategy.value", semantic_role="value"),
        )

    def run(self, view: object) -> StrategyDraft:
        latest = view.latest("value")  # type: ignore[attr-defined]
        total = float(latest["value"].sum())
        return StrategyDraft(
            weights=tuple(
                WeightEntry(instrument=row.instrument, weight=float(row.value) / total)
                for row in latest.itertuples()
            ),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
        )


def invocation(identity: str, hour: int) -> StrategyInvocation:
    return StrategyInvocation(
        invocation_id=identity,
        evaluation_time=datetime(2025, 1, 2, hour, tzinfo=UTC),
        config_fingerprint="config-1",
    )


def test_backtest_clock_is_aware_and_monotonic() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        BacktestClock(datetime(2025, 1, 2))

    clock = BacktestClock(datetime(2025, 1, 2, 9, tzinfo=UTC))
    with pytest.raises(ValueError, match="backwards"):
        clock.advance_to(datetime(2025, 1, 2, 8, tzinfo=UTC))


def test_future_observation_is_not_visible(tmp_path: Path) -> None:
    current, _ = project_with_market(tmp_path)

    morning = current.invoke(NormalizedValueStrategy(), invocation("morning", 9))
    afternoon = current.invoke(NormalizedValueStrategy(), invocation("afternoon", 16))

    assert morning.status is OutcomeStatus.COMPLETE
    assert {item.instrument: item.weight for item in morning.result.result.weights} == {
        "A": 0.25,
        "B": 0.75,
    }
    assert {item.instrument: item.weight for item in afternoon.result.result.weights} == {
        "A": 0.4,
        "B": 0.6,
    }
    access = morning.result.result.accesses[0]
    assert access.max_available_at == datetime(2025, 1, 2, 8, tzinfo=UTC)


def test_same_frozen_invocation_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    current, _ = project_with_market(tmp_path)
    selected = invocation("repeat", 9)

    first = current.invoke(NormalizedValueStrategy(), selected)
    second = current.invoke(NormalizedValueStrategy(), selected)

    assert first.result.result == second.result.result
    assert first.result.artifact.artifact_id == second.result.artifact.artifact_id


class FlexibleStrategy(NormalizedValueStrategy):
    strategy_id = "tests.flexible"

    def run(self, view: object) -> StrategyDraft:
        latest = view.latest("value")  # type: ignore[attr-defined]
        return StrategyDraft(
            weights=tuple(
                WeightEntry(instrument=row.instrument, weight=0.2)
                for row in latest.itertuples()
            ),
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
        )


def test_flexible_budget_residual_is_not_normalized(tmp_path: Path) -> None:
    current, _ = project_with_market(tmp_path)
    outcome = current.invoke(FlexibleStrategy(), invocation("flexible", 9))

    assert outcome.result.result.invested_gross == 0.4
    assert outcome.result.result.residual_budget == 0.6


class UndeclaredAccessStrategy(NormalizedValueStrategy):
    strategy_id = "tests.undeclared"

    def run(self, view: object) -> StrategyDraft:
        view.latest("sector")  # type: ignore[attr-defined]
        raise AssertionError("unreachable")


def test_undeclared_role_and_source_drift_fail_as_evidence(tmp_path: Path) -> None:
    current, source = project_with_market(tmp_path)
    undeclared = current.invoke(UndeclaredAccessStrategy(), invocation("undeclared", 9))
    assert undeclared.status is OutcomeStatus.FAILED
    assert undeclared.errors[0].error_code == "STRATEGY_RUN_FAILED"

    source.write_text(source.read_text(encoding="utf-8") + "2025-01-03T08:00:00Z,A,4.0\n")
    drifted = current.invoke(NormalizedValueStrategy(), invocation("drifted", 9))
    assert drifted.status is OutcomeStatus.FAILED
    assert "no longer matches registration" in drifted.errors[0].context["message"]


class HorizonStrategy(NormalizedValueStrategy):
    strategy_id = "tests.horizon"
    called = False

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return (
            ComponentRequirement(requirement_id="label.horizon_end", semantic_role="horizon_end"),
        )

    def run(self, view: object) -> StrategyDraft:
        self.called = True
        raise AssertionError("must not run without horizon_end")


def test_missing_horizon_requirement_fails_before_strategy_calculation(
    tmp_path: Path,
) -> None:
    current, _ = project_with_market(tmp_path)
    strategy = HorizonStrategy()

    outcome = current.invoke(strategy, invocation("horizon", 9))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].requirement_id == "label.horizon_end"
    assert strategy.called is False
    assert current.artifacts.list_envelopes() == ()
    assert len(current.artifacts.list_envelopes(include_failure=True)) == 1
