"""Public package surface for qlibx."""

from qlibx.errors import OperationError, OperationOutcome, OutcomeStatus
from qlibx.models import QlibxModel
from qlibx.onboarding import AgentTarget, OnboardingRequest
from qlibx.operations import StrategyInvocation
from qlibx.project import QlibxProject

__all__ = [
    "AgentTarget",
    "OnboardingRequest",
    "OperationError",
    "OperationOutcome",
    "OutcomeStatus",
    "QlibxModel",
    "QlibxProject",
    "StrategyInvocation",
    "main",
]


def main() -> None:
    """Run the package CLI."""
    from qlibx.cli import main as cli_main

    cli_main()
