from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.domain.identifiers import agenda_id
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import ConstraintSet, RunDefinition, StrategyConfig
from vqapr.runtime.agendas import OperationRole
from vqapr.valuation.configuration import ValuationConfig


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
        DataRequirement.of(
            "valuation",
            "prices",
            fields=("close",),
            lookback=RowsLookback(1),
        ),
    )


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
        ValuationConfig(
            agenda_id("valuation"),
            OperationRole.MONITORING,
            _valuation().mark_requirement,
        )
    with pytest.raises(ValueError, match="monitoring agenda_role"):
        MonitoringPolicy(agenda_id("monitoring"), OperationRole.VALUATION)


def test_valuation_requires_one_explicit_mark_field() -> None:
    with pytest.raises(ValueError, match="exactly one mark field"):
        ValuationConfig(
            agenda_id("valuation"),
            OperationRole.VALUATION,
            DataRequirement.of(
                "valuation",
                "prices",
                fields=("open", "close"),
                lookback=RowsLookback(1),
            ),
        )


def test_monitoring_policy_cannot_select_constraints() -> None:
    assert [field.name for field in fields(MonitoringPolicy)] == ["agenda_id", "agenda_role"]


def test_run_definition_retains_one_shared_constraint_set() -> None:
    constraints = ConstraintSet((_component(ComponentKind.CONSTRAINT, "no-short"),))
    run = RunDefinition(
        StrategyConfig(
            _component(ComponentKind.STRATEGY_MODEL, "strategy"),
            agenda_id("strategy"),
            OperationRole.STRATEGY_CALLBACK,
        ),
        _valuation(),
        constraints,
        MonitoringPolicy(agenda_id("monitoring"), OperationRole.MONITORING),
    )

    assert run.constraints is constraints


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
