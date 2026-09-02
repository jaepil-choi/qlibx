from __future__ import annotations

from dataclasses import fields
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.domain.identifiers import agenda_id
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import ConstraintSet, RunDefinition, StrategyConfig, StrategyEntry
from vqapr.runtime.agendas import OperationRole
from vqapr.valuation.configuration import ValuationConfig

KST = ZoneInfo("Asia/Seoul")


def _component(kind: ComponentKind, name: str) -> ComponentRef:
    return ComponentRef.of(
        name,
        kind,
        Path(f"{name}.py"),
        "Component",
        fingerprint="0" * 64,
    )


def _valuation() -> ValuationConfig:
    return ValuationConfig(
        agenda_id("valuation"),
        OperationRole.VALUATION,
    )


def _definition(**overrides: object) -> RunDefinition:
    declared: dict[str, object] = {
        "run_id": "r",
        "strategies": (StrategyEntry("strategy", ("no-short",)),),
        "valuation": _valuation(),
        "instruments": ("ABC",),
        "monitoring": MonitoringPolicy(agenda_id("monitoring"), OperationRole.MONITORING),
    }
    declared.update(overrides)
    return RunDefinition(**declared)  # type: ignore[arg-type]


def test_owner_configs_require_their_agenda_roles() -> None:
    strategy = _component(ComponentKind.STRATEGY_MODEL, "strategy")

    config = StrategyConfig(strategy, agenda_id("strategy"), OperationRole.STRATEGY_CALLBACK)

    assert config.agenda_role is OperationRole.STRATEGY_CALLBACK
    assert _valuation().agenda_role is OperationRole.VALUATION
    assert (
        MonitoringPolicy(agenda_id("monitoring"), OperationRole.MONITORING).agenda_role
        is OperationRole.MONITORING
    )

    with pytest.raises(ValueError, match="strategy agenda_role"):
        StrategyConfig(strategy, agenda_id("strategy"), OperationRole.VALUATION)
    with pytest.raises(ValueError, match="valuation agenda_role"):
        ValuationConfig(agenda_id("valuation"), OperationRole.MONITORING)
    with pytest.raises(ValueError, match="monitoring agenda_role"):
        MonitoringPolicy(agenda_id("monitoring"), OperationRole.VALUATION)


def test_valuation_declares_no_data_requirement() -> None:
    """Valuation subscribes to nothing.

    The book is valued from the prices the venue published as executable at the execution
    instant, which the run already reads to fill against. A second price source would give one
    run two answers for what its own book is worth.
    """
    assert [field.name for field in fields(ValuationConfig)] == ["agenda_id", "agenda_role"]


def test_monitoring_policy_cannot_select_constraints() -> None:
    assert [field.name for field in fields(MonitoringPolicy)] == ["agenda_id", "agenda_role"]


def test_a_run_names_its_strategies_and_each_strategy_its_constraints() -> None:
    """Record `139`: the run layer is shared; constraints belong to the strategy that runs under them."""
    run = _definition(
        strategies=(StrategyEntry("a", ("no-short",)), StrategyEntry("b")),
    )

    assert [entry.component_id for entry in run.strategies] == ["a", "b"]
    assert run.strategy("a").constraints == ("no-short",)
    assert run.strategy("b").constraints == ()
    assert "constraints" not in {field.name for field in fields(RunDefinition)}
    assert "strategy" not in {field.name for field in fields(RunDefinition)}
    with pytest.raises(KeyError, match="does not name strategy 'c'"):
        run.strategy("c")


def test_a_run_names_each_strategy_at_most_once_and_at_least_one() -> None:
    with pytest.raises(ValueError, match="at most once"):
        _definition(strategies=(StrategyEntry("a"), StrategyEntry("a")))
    with pytest.raises(ValueError, match="at least one strategy"):
        _definition(strategies=())


def test_a_strategy_entry_is_ids_and_memory_only() -> None:
    entry = StrategyEntry("a", ("x", "y"), {"cadence": [1]})
    assert entry.initial_model_memory == {"cadence": [1]}
    with pytest.raises(ValueError, match="repeat"):
        StrategyEntry("a", ("x", "x"))
    with pytest.raises(TypeError, match="component ids"):
        StrategyEntry("a", (_component(ComponentKind.CONSTRAINT, "x"),))  # type: ignore[arg-type]


def test_the_run_layer_pairs_its_declarations() -> None:
    with pytest.raises(ValueError, match="declared together"):
        _definition(exchange="venue")
    with pytest.raises(ValueError, match="declared together"):
        _definition(start=datetime(2024, 1, 2, tzinfo=KST))
    with pytest.raises(ValueError, match="start must not be after end"):
        _definition(start=datetime(2024, 1, 3, tzinfo=KST), end=datetime(2024, 1, 2, tzinfo=KST))
    with pytest.raises(ValueError, match="instruments must be unique"):
        _definition(instruments=("A", "A"))


def test_constraint_set_holds_constraint_refs_only() -> None:
    constraints = ConstraintSet((_component(ComponentKind.CONSTRAINT, "no-short"),))
    assert constraints.constraints[0].component_id == "no-short"
    with pytest.raises(ValueError, match="CONSTRAINT"):
        ConstraintSet((_component(ComponentKind.STRATEGY_MODEL, "s"),))


def test_run_definition_has_no_agenda_override() -> None:
    assert "agenda_id" not in {field.name for field in fields(RunDefinition)}
    assert "agenda_role" not in {field.name for field in fields(RunDefinition)}


def test_component_kinds_remain_closed_to_the_existing_four() -> None:
    assert tuple(ComponentKind) == (
        ComponentKind.DATA_MODEL,
        ComponentKind.STRATEGY_MODEL,
        ComponentKind.EXCHANGE,
        ComponentKind.CONSTRAINT,
    )
