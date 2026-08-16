"""vqapr의 유일한 documented Python surface.

사용자와 agent는 이 module에서 config 타입과 operation을 가져온다. 내부 module 경로는 공개 계약이
아니다.
"""

from __future__ import annotations

from pathlib import Path

from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data.datasets import DatasetRegistration, validate
from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import VqaprError
from vqapr.exchange.conventions import FillConvention
from vqapr.exchange.execution_table import (
    ExecutionInputRegistration,
    ExecutionTableSpec,
    validate_execution_input,
)
from vqapr.extension.component import ComponentRef
from vqapr.extension.registration import register_data_model
from vqapr.flow.materialize import MaterializationResult, MaterializationSpec, materialize
from vqapr.flow.run import StrategyConfig
from vqapr.models.contexts import DataModelContext
from vqapr.models.data_model import DataModel
from vqapr.runtime.agendas import OperationAgenda
from vqapr.valuation.configuration import ValuationConfig
from vqapr.workspace import Workspace

__all__ = (
    "CalendarLookback",
    "ComponentRef",
    "DataModel",
    "DataModelContext",
    "DataRequirement",
    "DatasetRegistration",
    "ExecutionInputRegistration",
    "ExecutionTableSpec",
    "FillConvention",
    "MaterializationResult",
    "MaterializationSpec",
    "MonitoringPolicy",
    "OperationAgenda",
    "RowsLookback",
    "SourceSpec",
    "StrategyConfig",
    "ValuationConfig",
    "VqaprError",
    "materialize",
    "register_agenda",
    "register_data_model",
    "register_dataset",
    "register_execution_input",
    "register_monitoring_policy",
    "register_strategy_config",
    "register_valuation_config",
)


def register_dataset(
    project_root: str | Path,
    registration: DatasetRegistration,
    source: SourceSpec,
) -> bool:
    """준비된 parquet을 검증하고 project workspace에 등록한다.

    새 등록이면 ``True``, 디스크에 이미 같은 선언이 있으면 ``False``다. 검증이나 persistence가
    실패하면 ``VqaprError``를 발생시키며, 검증 실패는 workspace를 만들거나 바꾸지 않는다.
    """
    diagnosis, _ = validate(registration, source)
    diagnosis.raise_if_failed()
    return Workspace.create(project_root).register_dataset(registration, source)


def register_execution_input(
    project_root: str | Path,
    registration: ExecutionInputRegistration,
) -> bool:
    """준비된 execution parquet과 fill binding을 검증하고 project에 등록한다."""
    diagnosis = validate_execution_input(registration)
    diagnosis.raise_if_failed()
    return Workspace.create(project_root).register_execution_input(registration)


def register_agenda(project_root: str | Path, agenda: OperationAgenda) -> bool:
    return Workspace.create(project_root).register_agenda(agenda)


def register_strategy_config(project_root: str | Path, config: StrategyConfig) -> bool:
    return Workspace.create(project_root).register_strategy_config(config)


def register_valuation_config(project_root: str | Path, config: ValuationConfig) -> bool:
    return Workspace.create(project_root).register_valuation_config(config)


def register_monitoring_policy(project_root: str | Path, policy: MonitoringPolicy) -> bool:
    return Workspace.create(project_root).register_monitoring_policy(policy)
