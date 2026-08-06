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

__all__ = [
    "ExtensionRegistration",
    "ExtensionValidationRequest",
    "NeutralizationExtensionSpec",
    "NeutralizationInput",
    "NeutralizationInputRow",
    "NeutralizationResult",
    "NeutralizedValue",
    "group_demean",
]
