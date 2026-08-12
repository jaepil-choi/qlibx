"""Public contracts and built-in examples for project-local extensions."""

from qlibx.extensions.builtins import group_demean
from qlibx.extensions.contracts import (
    ExtensionRegistration,
    ExtensionValidationRequest,
    NeutralizationExtensionSpec,
    NeutralizationInput,
    NeutralizationInputRow,
    NeutralizationResult,
    NeutralizedValue,
)
from qlibx.extensions.strategy import (
    RegisteredStrategyExtension,
    StrategyArtifactModelRegistration,
    StrategyArtifactModelSpec,
    StrategyExtensionRegistration,
    StrategyExtensionSpec,
    StrategyExtensionValidationRequest,
    StrategyExtensionValidationResult,
)

__all__ = [
    "ExtensionRegistration",
    "ExtensionValidationRequest",
    "NeutralizationExtensionSpec",
    "NeutralizationInput",
    "NeutralizationInputRow",
    "NeutralizationResult",
    "NeutralizedValue",
    "RegisteredStrategyExtension",
    "StrategyArtifactModelRegistration",
    "StrategyArtifactModelSpec",
    "StrategyExtensionRegistration",
    "StrategyExtensionSpec",
    "StrategyExtensionValidationRequest",
    "StrategyExtensionValidationResult",
    "group_demean",
]
