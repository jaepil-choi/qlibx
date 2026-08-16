from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import VqaprError
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.flow.preflight import preflight_run
from vqapr.flow.run import ConstraintSet, RunDefinition, StrategyConfig
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.valuation.configuration import ValuationConfig
from vqapr.workspace import Workspace

_ZONE = ZoneInfo("Asia/Seoul")


def _occurrence(identifier: str, role: OperationRole, hour: int) -> OperationOccurrence:
    return OperationOccurrence(
        identifier,
        role,
        LocalInstantDeclaration(date(2024, 3, 5), time(hour), "Asia/Seoul", 0, "+09:00"),
    )


def _agenda(identifier: str, role: OperationRole, *hours: int) -> OperationAgenda:
    return OperationAgenda.from_occurrences(
        agenda_id=identifier,
        role=role,
        timezone="Asia/Seoul",
        occurrences=tuple(_occurrence(f"{identifier}-{hour}", role, hour) for hour in hours),
        provenance="test fixture",
    )


def _component(root: Path, identifier: str, kind: ComponentKind) -> ComponentRef:
    path = root / f"{identifier}.py"
    path.write_text(f"class {identifier.title().replace('-', '')}:\n    pass\n", encoding="utf-8")
    return ComponentRef.of(
        identifier,
        kind,
        path,
        identifier.title().replace("-", ""),
        fingerprint=fingerprint_component(
            path, kind=kind, object_name=identifier.title().replace("-", "")
        ),
    )


def _setup(root: Path, model_price_parquet: Path) -> tuple[Workspace, RunDefinition]:
    workspace = Workspace.create(root)
    strategy_component = _component(root, "strategy", ComponentKind.STRATEGY_MODEL)
    constraint_component = _component(root, "limit", ComponentKind.CONSTRAINT)
    for component in (strategy_component, constraint_component):
        workspace.register_component(component)
    workspace.register_dataset(
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("session_date", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("prices-source", model_price_parquet),
    )
    strategy_agenda = _agenda("strategy", OperationRole.STRATEGY_CALLBACK, 9, 10)
    valuation_agenda = _agenda("valuation", OperationRole.VALUATION, 9)
    monitoring_agenda = _agenda("monitoring", OperationRole.MONITORING, 11)
    for agenda in (strategy_agenda, valuation_agenda, monitoring_agenda):
        workspace.register_agenda(agenda)
    strategy = StrategyConfig(strategy_component, "strategy", OperationRole.STRATEGY_CALLBACK)
    valuation = ValuationConfig(
        "valuation",
        OperationRole.VALUATION,
        DataRequirement.of("valuation", "prices", fields=("close",), lookback=RowsLookback(1)),
    )
    monitoring = MonitoringPolicy("monitoring", OperationRole.MONITORING)
    workspace.register_strategy_config(strategy)
    workspace.register_valuation_config(valuation)
    workspace.register_monitoring_policy(monitoring)
    return workspace, RunDefinition(
        strategy,
        valuation,
        ConstraintSet((constraint_component,)),
        monitoring,
        start=datetime(2024, 3, 5, 9, tzinfo=_ZONE),
        end=datetime(2024, 3, 5, 10, tzinfo=_ZONE),
        initial_account={"cash": 100},
        initial_model_state={"version": "fresh"},
    )


def test_preflight_freezes_independent_inclusive_slices_and_static_merge(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace, definition = _setup(tmp_path, model_price_parquet)

    frozen = preflight_run(workspace, definition)

    assert [item.occurrence_id for item in frozen.strategy_agenda.occurrences] == [
        "strategy-9",
        "strategy-10",
    ]
    assert [item.occurrence_id for item in frozen.valuation_agenda.occurrences] == ["valuation-9"]
    assert frozen.monitoring_agenda is not None
    assert frozen.monitoring_agenda.occurrences == ()
    assert [item.occurrence_id for item in frozen.static_occurrences] == [
        "strategy-9",
        "valuation-9",
        "strategy-10",
    ]
    assert frozen.constraints is not definition.constraints
    assert frozen.constraints.constraints[0].component_id == "limit"
    assert frozen.identity == preflight_run(workspace, definition).identity
    assert (
        frozen.physical_source_guarantee
        == "Configuration and declaration objects are frozen; physical source bytes are not."
    )


def test_preflight_is_detached_and_rejects_reference_or_component_drift(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace, definition = _setup(tmp_path, model_price_parquet)
    frozen = preflight_run(workspace, definition)
    definition.strategy.component.config["changed"] = 1

    assert frozen.strategy.component.config == {}
    with pytest.raises(ValueError, match="strategy configuration reference drift"):
        preflight_run(workspace, definition)

    workspace, definition = _setup(tmp_path / "drift", model_price_parquet)
    (tmp_path / "drift" / "strategy.py").write_text(
        "class Strategy:\n    changed = True\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="fingerprint drift"):
        preflight_run(workspace, definition)


def test_preflight_rejects_missing_requirement_and_invalid_bounds(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    workspace, definition = _setup(tmp_path, model_price_parquet)
    missing = ValuationConfig(
        "valuation",
        OperationRole.VALUATION,
        DataRequirement.of("valuation", "absent", fields=("close",), lookback=RowsLookback(1)),
    )
    workspace._valuation_configs["valuation"] = missing
    invalid = RunDefinition(
        definition.strategy,
        missing,
        definition.constraints,
        definition.monitoring,
        start=definition.start,
        end=definition.end,
    )
    with pytest.raises(VqaprError):
        preflight_run(workspace, invalid)
    with pytest.raises(ValueError, match="timezone-aware"):
        RunDefinition(
            definition.strategy,
            definition.valuation,
            definition.constraints,
            start=datetime(2024, 3, 5, 9),
            end=definition.end,
        )
    with pytest.raises(ValueError, match="start must not be after end"):
        RunDefinition(
            definition.strategy,
            definition.valuation,
            definition.constraints,
            start=definition.end,
            end=definition.start,
        )
