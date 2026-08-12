"""Flow-owned resolution of typed Strategy artifact inputs."""

import hashlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from qlibx.contracts import (
    StoredSignalResult,
    StrategyArtifactBinding,
    StrategyArtifactRequirement,
)
from qlibx.errors import CommitStatus, OperationError, OutcomeStatus
from qlibx.evidence import ArtifactContract, LocalArtifactBackend
from qlibx.flow.strategy_results import (
    STRATEGY_RESULT_CONTRACT,
)
from qlibx.models import QlibxModel
from qlibx.view import ArtifactInputProjection

STORED_SIGNAL_CONTRACT = ArtifactContract(
    artifact_type="stored_signal_result",
    artifact_schema_version=1,
    payload_model=StoredSignalResult,
)

BUILT_IN_STRATEGY_ARTIFACT_CONTRACTS = (
    STORED_SIGNAL_CONTRACT,
    STRATEGY_RESULT_CONTRACT,
)


class StrategyArtifactContractRegistry:
    """Immutable operation-scoped artifact contract lookup."""

    def __init__(self, contracts: Iterable[ArtifactContract] = ()) -> None:
        indexed: dict[tuple[str, int], ArtifactContract] = {}
        for contract in contracts:
            key = (contract.artifact_type, contract.artifact_schema_version)
            if key in indexed:
                raise ValueError(f"duplicate Strategy artifact contract: {key[0]}:v{key[1]}")
            indexed[key] = contract
        self._contracts = indexed

    @classmethod
    def built_in(cls) -> "StrategyArtifactContractRegistry":
        return cls(BUILT_IN_STRATEGY_ARTIFACT_CONTRACTS)

    def extended(
        self,
        contracts: Iterable[ArtifactContract],
    ) -> "StrategyArtifactContractRegistry":
        return StrategyArtifactContractRegistry((*self._contracts.values(), *contracts))

    def get(self, artifact_type: str, version: int) -> ArtifactContract | None:
        return self._contracts.get((artifact_type, version))

    def supported_contracts(self) -> tuple[str, ...]:
        return tuple(
            f"{artifact_type}:v{version}" for artifact_type, version in sorted(self._contracts)
        )


@dataclass(frozen=True, slots=True)
class StrategyArtifactResolution:
    projections: tuple[ArtifactInputProjection, ...] = ()
    errors: tuple[OperationError, ...] = ()

    @property
    def failed(self) -> bool:
        return bool(self.errors)


class StrategyArtifactResolver:
    """Validate exact frozen bindings and remove backend authority from Strategy inputs."""

    def resolve(
        self,
        *,
        invocation_id: str,
        requirements: tuple[StrategyArtifactRequirement, ...],
        bindings: tuple[StrategyArtifactBinding, ...],
        artifacts: LocalArtifactBackend,
        contract_registry: StrategyArtifactContractRegistry | None = None,
        operation: str = "strategy.run",
    ) -> StrategyArtifactResolution:
        selected_registry = contract_registry or StrategyArtifactContractRegistry.built_in()
        declaration_errors = self._validate_cardinality(
            operation=operation,
            invocation_id=invocation_id,
            requirements=requirements,
            bindings=bindings,
        )
        if declaration_errors:
            return StrategyArtifactResolution(errors=declaration_errors)

        binding_by_role = {binding.consumer_role: binding for binding in bindings}
        projections: list[ArtifactInputProjection] = []
        for requirement in requirements:
            contract = selected_registry.get(
                requirement.artifact_type,
                requirement.artifact_schema_version,
            )
            if contract is None:
                return StrategyArtifactResolution(
                    errors=(
                        self._error(
                            operation=operation,
                            invocation_id=invocation_id,
                            requirement=requirement,
                            error_code="STRATEGY_ARTIFACT_CONTRACT_UNSUPPORTED",
                            expected_contract=self._contract_context(requirement),
                            actual_contract=None,
                            context={
                                "supported_contracts": selected_registry.supported_contracts()
                            },
                        ),
                    )
                )

            binding = binding_by_role[requirement.consumer_role]
            loaded = artifacts.load_model(binding.artifact_id, contract)
            if loaded.status is not OutcomeStatus.COMPLETE:
                backend_error = loaded.errors[0] if loaded.errors else None
                actual_contract = None
                if backend_error is not None:
                    actual_contract = {
                        "artifact_type": backend_error.context.get("actual_type"),
                        "artifact_schema_version": backend_error.context.get("actual_version"),
                        "backend_error_code": backend_error.error_code,
                    }
                return StrategyArtifactResolution(
                    errors=(
                        self._error(
                            operation=operation,
                            invocation_id=invocation_id,
                            requirement=requirement,
                            error_code="STRATEGY_ARTIFACT_CONTRACT_UNSUPPORTED",
                            artifact_id=binding.artifact_id,
                            expected_contract=self._contract_context(requirement),
                            actual_contract=actual_contract,
                            context={
                                "backend_stage": (
                                    backend_error.stage_path if backend_error is not None else None
                                )
                            },
                        ),
                    )
                )

            payload = loaded.result.payload
            semantic_error = self._semantic_error(
                operation=operation,
                invocation_id=invocation_id,
                requirement=requirement,
                artifact_id=binding.artifact_id,
                payload=payload,
            )
            if semantic_error is not None:
                return StrategyArtifactResolution(errors=(semantic_error,))

            envelope = loaded.result.envelope
            projections.append(
                ArtifactInputProjection(
                    requirement_id=requirement.requirement_id,
                    consumer_role=requirement.consumer_role,
                    artifact_id=envelope.artifact_id,
                    artifact_type=envelope.artifact_type,
                    artifact_schema_version=envelope.artifact_schema_version,
                    content_hash=envelope.content_hash,
                    payload=payload,
                )
            )
        return StrategyArtifactResolution(projections=tuple(projections))

    def _validate_cardinality(
        self,
        *,
        operation: str,
        invocation_id: str,
        requirements: tuple[StrategyArtifactRequirement, ...],
        bindings: tuple[StrategyArtifactBinding, ...],
    ) -> tuple[OperationError, ...]:
        errors: list[OperationError] = []
        requirement_ids = [requirement.requirement_id for requirement in requirements]
        requirement_roles = [requirement.consumer_role for requirement in requirements]
        binding_roles = [binding.consumer_role for binding in bindings]

        for duplicate in self._duplicates(requirement_ids):
            errors.append(
                self._declaration_error(
                    operation,
                    invocation_id,
                    "duplicate_requirement_id",
                    duplicate,
                )
            )
        for duplicate in self._duplicates(requirement_roles):
            errors.append(
                self._declaration_error(
                    operation,
                    invocation_id,
                    "duplicate_consumer_role",
                    duplicate,
                )
            )
        for duplicate in self._duplicates(binding_roles):
            errors.append(
                self._declaration_error(
                    operation,
                    invocation_id,
                    "duplicate_binding_role",
                    duplicate,
                )
            )
        if errors:
            return tuple(errors)

        requirement_by_role = {
            requirement.consumer_role: requirement for requirement in requirements
        }
        binding_role_set = set(binding_roles)
        for requirement in requirements:
            if requirement.consumer_role not in binding_role_set:
                errors.append(
                    self._error(
                        operation=operation,
                        invocation_id=invocation_id,
                        requirement=requirement,
                        error_code="STRATEGY_ARTIFACT_BINDING_MISSING",
                        expected_contract=self._contract_context(requirement),
                        actual_contract=None,
                    )
                )
        for binding in bindings:
            if binding.consumer_role not in requirement_by_role:
                errors.append(
                    self._error(
                        operation=operation,
                        invocation_id=invocation_id,
                        requirement=None,
                        error_code="STRATEGY_ARTIFACT_BINDING_UNDECLARED",
                        artifact_id=binding.artifact_id,
                        consumer_role=binding.consumer_role,
                        expected_contract=None,
                        actual_contract={"artifact_id": binding.artifact_id},
                    )
                )
        return tuple(errors)

    def _semantic_error(
        self,
        *,
        operation: str,
        invocation_id: str,
        requirement: StrategyArtifactRequirement,
        artifact_id: str,
        payload: QlibxModel,
    ) -> OperationError | None:
        values = payload.model_dump(mode="python")
        for constraint in requirement.semantic_constraints:
            if constraint.field not in values:
                actual = {"field": constraint.field, "present": False}
            else:
                value = values[constraint.field]
                if type(value) is type(constraint.expected) and value == constraint.expected:
                    continue
                actual = {
                    "field": constraint.field,
                    "present": True,
                    "value": value,
                    "value_type": type(value).__name__,
                }
            return self._error(
                operation=operation,
                invocation_id=invocation_id,
                requirement=requirement,
                error_code="STRATEGY_ARTIFACT_SEMANTICS_INCOMPATIBLE",
                artifact_id=artifact_id,
                expected_contract={
                    **self._contract_context(requirement),
                    "semantic_field": constraint.field,
                    "semantic_value": constraint.expected,
                    "semantic_value_type": type(constraint.expected).__name__,
                },
                actual_contract=actual,
            )
        return None

    def _declaration_error(
        self,
        operation: str,
        invocation_id: str,
        issue: str,
        value: str,
    ) -> OperationError:
        return self._error(
            operation=operation,
            invocation_id=invocation_id,
            requirement=None,
            error_code="STRATEGY_ARTIFACT_REQUIREMENTS_FAILED",
            expected_contract={"cardinality": "unique"},
            actual_contract={"issue": issue, "duplicate_value": value},
        )

    @staticmethod
    def _duplicates(values: list[str]) -> tuple[str, ...]:
        return tuple(sorted(value for value, count in Counter(values).items() if count > 1))

    @staticmethod
    def _contract_context(requirement: StrategyArtifactRequirement) -> dict[str, object]:
        return {
            "artifact_type": requirement.artifact_type,
            "artifact_schema_version": requirement.artifact_schema_version,
        }

    @staticmethod
    def _error(
        *,
        operation: str,
        invocation_id: str,
        requirement: StrategyArtifactRequirement | None,
        error_code: str,
        expected_contract: dict[str, object] | None,
        actual_contract: dict[str, object] | None,
        artifact_id: str | None = None,
        consumer_role: str | None = None,
        context: dict[str, object] | None = None,
    ) -> OperationError:
        role = consumer_role or (requirement.consumer_role if requirement is not None else None)
        requirement_id = requirement.requirement_id if requirement is not None else None
        seed = hashlib.sha256(
            (
                f"{invocation_id}:{operation}.artifacts:{error_code}:"
                f"{requirement_id}:{role}:{artifact_id}"
            ).encode()
        ).hexdigest()[:24]
        bounded_context = {
            "consumer_role": role,
            "artifact_id": artifact_id,
            "actual_contract": actual_contract,
            **(context or {}),
        }
        return OperationError(
            operation=operation,
            stage_path=(f"{operation}.artifacts.{role}" if role else f"{operation}.artifacts"),
            error_code=error_code,
            requirement_id=requirement_id,
            expected=expected_contract,
            context=bounded_context,
            commit_status=CommitStatus.NONE,
            retry_preconditions=("correct the Strategy artifact declaration or frozen binding",),
            idempotency_identity=invocation_id,
            error_id=f"error-{seed}",
        )
