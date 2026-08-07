"""Public package surface for qlibx."""

from qlibx.constraints import (
    ConstraintAdjustmentSpec,
    ConstraintMonitoringSpec,
    ConstraintValidationSpec,
    MvpConstraintPolicy,
)
from qlibx.errors import OperationError, OperationOutcome, OutcomeStatus
from qlibx.execution import (
    CostRule,
    EtfInstrument,
    KrxExchangeConfig,
    Side,
    StockInstrument,
)
from qlibx.models import QlibxModel
from qlibx.onboarding import AgentTarget, OnboardingDesiredState, OnboardingRequest
from qlibx.operations import StrategyInvocation
from qlibx.portfolio import ExecutionLotInput
from qlibx.project import QlibxProject
from qlibx.simulation import DailyAccountSeed, DailyMarketBinding, DailySimulationSpec

__all__ = [
    "AgentTarget",
    "ConstraintAdjustmentSpec",
    "ConstraintMonitoringSpec",
    "ConstraintValidationSpec",
    "CostRule",
    "DailyAccountSeed",
    "DailyMarketBinding",
    "DailySimulationSpec",
    "EtfInstrument",
    "ExecutionLotInput",
    "KrxExchangeConfig",
    "MvpConstraintPolicy",
    "OnboardingDesiredState",
    "OnboardingRequest",
    "OperationError",
    "OperationOutcome",
    "OutcomeStatus",
    "QlibxModel",
    "QlibxProject",
    "Side",
    "StockInstrument",
    "StrategyInvocation",
    "main",
]


def main() -> None:
    """Run the package CLI."""
    from qlibx.cli import main as cli_main

    cli_main()
