"""Public package surface for qlibx."""

from qlibx.constraints import (
    ConstraintAdjustmentSpec,
    ConstraintMonitoringSpec,
    ConstraintValidationSpec,
    MvpConstraintPolicy,
)
from qlibx.context import StrategyView
from qlibx.data import ComponentRequirement
from qlibx.errors import OperationError, OperationOutcome, OutcomeStatus
from qlibx.execution import (
    CostRule,
    EtfInstrument,
    KrxExchangeConfig,
    Side,
    StockInstrument,
)
from qlibx.extensions import (
    RegisteredStrategyExtension,
    StrategyArtifactModelRegistration,
    StrategyArtifactModelSpec,
    StrategyExtensionRegistration,
    StrategyExtensionSpec,
    StrategyExtensionValidationRequest,
    StrategyExtensionValidationResult,
)
from qlibx.models import QlibxModel
from qlibx.onboarding import AgentTarget, OnboardingDesiredState, OnboardingRequest
from qlibx.operations import (
    ArtifactSemanticConstraint,
    BudgetMode,
    DecisionAction,
    StoredSignalEntry,
    StoredSignalResult,
    StrategyArtifactBinding,
    StrategyArtifactRequirement,
    StrategyDraft,
    StrategyInvocation,
    StrategyResult,
    WeightEntry,
)
from qlibx.portfolio import ExecutionLotInput
from qlibx.project import QlibxProject
from qlibx.simulation import DailyAccountSeed, DailyMarketBinding, DailySimulationSpec

__all__ = [
    "AgentTarget",
    "ArtifactSemanticConstraint",
    "BudgetMode",
    "ComponentRequirement",
    "ConstraintAdjustmentSpec",
    "ConstraintMonitoringSpec",
    "ConstraintValidationSpec",
    "CostRule",
    "DailyAccountSeed",
    "DailyMarketBinding",
    "DailySimulationSpec",
    "DecisionAction",
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
    "RegisteredStrategyExtension",
    "Side",
    "StockInstrument",
    "StoredSignalEntry",
    "StoredSignalResult",
    "StrategyArtifactBinding",
    "StrategyArtifactModelRegistration",
    "StrategyArtifactModelSpec",
    "StrategyArtifactRequirement",
    "StrategyDraft",
    "StrategyExtensionRegistration",
    "StrategyExtensionSpec",
    "StrategyExtensionValidationRequest",
    "StrategyExtensionValidationResult",
    "StrategyInvocation",
    "StrategyResult",
    "StrategyView",
    "WeightEntry",
    "main",
]


def main() -> None:
    """Run the package CLI."""
    from qlibx.cli import main as cli_main

    cli_main()
