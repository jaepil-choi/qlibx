"""Progressive operation requirement resolution."""

import hashlib
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from qlibx.data.contracts import RegisteredDataset
from qlibx.data.registry import RegistrySnapshot
from qlibx.errors import CommitStatus, OperationError
from qlibx.models import QlibxModel


class AxisRequirement(QlibxModel):
    kind: Literal["instrument"] = "instrument"


class TimeRequirement(QlibxModel):
    available_at_required: Literal[True] = True


class CompatibilityRule(QlibxModel):
    attribute: Literal["semantic_category", "source_provenance"]
    expected: str = Field(min_length=1)


class ComponentRequirement(QlibxModel):
    requirement_id: str = Field(min_length=1)
    semantic_role: str = Field(min_length=1)
    axis: AxisRequirement = AxisRequirement()
    time: TimeRequirement = TimeRequirement()
    compatibility: tuple[CompatibilityRule, ...] = ()
    dataset_id: str | None = None


class ResolvedBinding(QlibxModel):
    requirement_id: str
    semantic_role: str
    dataset_id: str
    field: str
    registration_identity: str


@dataclass(frozen=True, slots=True)
class Resolution:
    bindings: tuple[ResolvedBinding, ...]
    errors: tuple[OperationError, ...]

    @property
    def failed(self) -> bool:
        return bool(self.errors)


class RequirementResolver:
    """Resolve only declared semantic requirements from a frozen snapshot."""

    def resolve(
        self,
        *,
        operation: str,
        idempotency_identity: str,
        requirements: tuple[ComponentRequirement, ...],
        registry: RegistrySnapshot,
    ) -> Resolution:
        bindings: list[ResolvedBinding] = []
        errors: list[OperationError] = []
        for requirement in requirements:
            candidates = [
                dataset
                for dataset in registry.datasets
                if requirement.semantic_role in dataset.bindings
                and (requirement.dataset_id is None or dataset.dataset_id == requirement.dataset_id)
                and all(
                    getattr(dataset, rule.attribute) == rule.expected
                    for rule in requirement.compatibility
                )
            ]
            if not candidates:
                errors.append(
                    self._missing_error(operation, idempotency_identity, requirement)
                )
                continue
            candidates.sort(key=lambda item: item.dataset_id)
            if len(candidates) > 1:
                errors.append(
                    self._ambiguous_error(
                        operation,
                        idempotency_identity,
                        requirement,
                        candidates,
                    )
                )
                continue
            selected = candidates[0]
            bindings.append(
                ResolvedBinding(
                    requirement_id=requirement.requirement_id,
                    semantic_role=requirement.semantic_role,
                    dataset_id=selected.dataset_id,
                    field=selected.bindings[requirement.semantic_role],
                    registration_identity=selected.registration_identity,
                )
            )
        return Resolution(bindings=tuple(bindings), errors=tuple(errors))

    @staticmethod
    def _missing_error(
        operation: str,
        idempotency_identity: str,
        requirement: ComponentRequirement,
    ) -> OperationError:
        seed = (
            f"{operation}:{idempotency_identity}:{requirement.requirement_id}:"
            f"{requirement.semantic_role}"
        )
        error_id = hashlib.sha256(seed.encode()).hexdigest()[:24]
        return OperationError(
            operation=operation,
            stage_path=f"{operation}.requirements.{requirement.semantic_role}",
            error_code="REQUIREMENT_NOT_RESOLVED",
            requirement_id=requirement.requirement_id,
            context={
                "semantic_role": requirement.semantic_role,
                "dataset_id": requirement.dataset_id,
            },
            commit_status=CommitStatus.NONE,
            retry_preconditions=("register or bind a compatible semantic capability",),
            idempotency_identity=idempotency_identity,
            error_id=f"error-{error_id}",
        )

    @staticmethod
    def _ambiguous_error(
        operation: str,
        idempotency_identity: str,
        requirement: ComponentRequirement,
        candidates: list[RegisteredDataset],
    ) -> OperationError:
        candidate_context = [
            {
                "dataset_id": candidate.dataset_id,
                "registration_identity": candidate.registration_identity,
            }
            for candidate in candidates
        ]
        candidate_identity = ":".join(
            f"{item['dataset_id']}={item['registration_identity']}"
            for item in candidate_context
        )
        seed = (
            f"{operation}:{idempotency_identity}:{requirement.requirement_id}:"
            f"{requirement.semantic_role}:{candidate_identity}"
        )
        error_id = hashlib.sha256(seed.encode()).hexdigest()[:24]
        return OperationError(
            operation=operation,
            stage_path=f"{operation}.requirements.{requirement.semantic_role}",
            error_code="REQUIREMENT_AMBIGUOUS",
            requirement_id=requirement.requirement_id,
            context={
                "semantic_role": requirement.semantic_role,
                "candidate_count": len(candidate_context),
                "candidates": candidate_context[:20],
            },
            commit_status=CommitStatus.NONE,
            retry_preconditions=(
                "set requirement.dataset_id to exactly one candidate or remove the "
                "duplicate binding",
            ),
            idempotency_identity=idempotency_identity,
            error_id=f"error-{error_id}",
        )
