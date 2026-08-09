"""Public package surface for qlibx."""

from qlibx.academic import (
    AcademicExchange,
    AcademicExchangeProfile,
    AcademicFill,
    AcademicInstrumentKind,
    AcademicInstrumentListing,
    AcademicPortfolioSnapshot,
    AcademicPortfolioState,
    AcademicPriceSemantics,
    AcademicRunSpec,
)
from qlibx.constraints import (
    ConstraintAdjustmentSpec,
    ConstraintMonitoringSpec,
    ConstraintValidationSpec,
    MvpConstraintPolicy,
)
from qlibx.context import MaterializeView, StrategyView
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
    ForwardReturnLabelEntry,
    ForwardReturnLabelModel,
    ForwardReturnLabelResult,
    MaterializationInvocation,
    MaterializationOperation,
    MaterializationOutputContract,
    StoredSignalEntry,
    StoredSignalResult,
    StrategyArtifactBinding,
    StrategyArtifactRequirement,
    StrategyDraft,
    StrategyInvocation,
    StrategyResult,
    StrategyResultV1,
    StrategySourceStateLineage,
    WeightEntry,
)
from qlibx.portfolio import ExecutionLotInput
from qlibx.project import QlibxProject
from qlibx.simulation import (
    DailyAccountSeed,
    DailyMarketBinding,
    DailySimulationSpec,
    FrozenDailyExecutionSpec,
)

__all__ = [
    "AcademicExchange",
    "AcademicExchangeProfile",
    "AcademicFill",
    "AcademicInstrumentKind",
    "AcademicInstrumentListing",
    "AcademicPortfolioSnapshot",
    "AcademicPortfolioState",
    "AcademicPriceSemantics",
    "AcademicRunSpec",
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
    "ForwardReturnLabelEntry",
    "ForwardReturnLabelModel",
    "ForwardReturnLabelResult",
    "FrozenDailyExecutionSpec",
    "KrxExchangeConfig",
    "MaterializationInvocation",
    "MaterializationOperation",
    "MaterializationOutputContract",
    "MaterializeView",
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
    "StrategyResultV1",
    "StrategySourceStateLineage",
    "StrategyView",
    "WeightEntry",
    "main",
]


def main() -> None:
    """Run the package CLI."""
    from qlibx.cli import main as cli_main

    cli_main()
