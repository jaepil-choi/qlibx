"""Validation and append-only registration of project-local Strategy modules."""

import hashlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from qlibx.account import Account, StrategyMemoryStore
from qlibx.analysis import SessionPerformanceEvidence
from qlibx.context import (
    AccountFeedbackState,
    AccountState,
    ArtifactInputProjection,
    ArtifactViewAccessError,
    MemoryState,
    StrategyView,
    ViewAccessError,
    ViewGate,
)
from qlibx.data import (
    ComponentRequirement,
    ObservationStore,
    RegistrySnapshot,
    RequirementResolver,
    ResolvedBinding,
)
from qlibx.errors import OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import ArtifactContract, DependencyEdge, LocalArtifactBackend
from qlibx.extensions import (
    RegisteredStrategyExtension,
    StrategyArtifactModelRegistration,
    StrategyExtensionRegistration,
    StrategyExtensionSpec,
    StrategyExtensionValidationRequest,
    StrategyExtensionValidationResult,
)
from qlibx.extensions.local_modules import (
    LoadedLocalModule,
    LocalModuleLoader,
    LocalModuleSourceDriftError,
)
from qlibx.flow.analysis import SIMULATION_CHECKPOINT_CONTRACT
from qlibx.flow.artifact_inputs import (
    StrategyArtifactContractRegistry,
    StrategyArtifactResolver,
)
from qlibx.flow.failures import (
    build_operation_error,
    publish_failed_errors,
    publish_failed_outcome,
)
from qlibx.kernel import BacktestClock
from qlibx.models import QlibxModel
from qlibx.operations import (
    StrategyArtifactRequirement,
    StrategyDraft,
    StrategyOperation,
)

STRATEGY_EXTENSION_REGISTRATION_CONTRACT = ArtifactContract(
    artifact_type="strategy_extension_registration",
    artifact_schema_version=1,
    payload_model=StrategyExtensionRegistration,
)

SESSION_PERFORMANCE_CONTRACT = ArtifactContract(
    artifact_type="session_performance",
    artifact_schema_version=1,
    payload_model=SessionPerformanceEvidence,
)


@dataclass(frozen=True, slots=True)
class _PublishedPerformance:
    artifact_id: str
    record: SessionPerformanceEvidence


@dataclass(frozen=True, slots=True)
class _ModuleContract:
    loaded: LoadedLocalModule
    spec: StrategyExtensionSpec
    first: StrategyOperation
    second: StrategyOperation
    dataset_requirements: tuple[ComponentRequirement, ...]
    artifact_requirements: tuple[StrategyArtifactRequirement, ...]
    artifact_models: tuple[StrategyArtifactModelRegistration, ...]
    artifact_contracts: StrategyArtifactContractRegistry


@dataclass(frozen=True, slots=True)
class LoadedStrategyExtension:
    registration_artifact_id: str
    registration: StrategyExtensionRegistration
    operation: StrategyOperation
    artifact_contracts: StrategyArtifactContractRegistry


@dataclass(frozen=True, slots=True)
class _FixtureState:
    account_state: AccountState | None = None
    account_feedback: AccountFeedbackState | None = None
    memory_state: MemoryState | None = None
    session_performance: _PublishedPerformance | None = None


class _ContractError(ValueError):
    def __init__(self, code: str, message: str, context: dict[str, object] | None = None) -> None:
        self.code = code
        self.context = context or {}
        super().__init__(message)


class StrategyExtensionFlow:
    """Prove a trusted local Strategy against a frozen package-owned fixture."""

    operation = "strategy_extension.validate"

    def __init__(
        self,
        *,
        project_root: Path,
        extension_root: Path,
        registry: RegistrySnapshot,
        artifacts: LocalArtifactBackend,
        resolver: RequirementResolver | None = None,
        store: ObservationStore | None = None,
    ) -> None:
        self._module_loader = LocalModuleLoader(
            project_root=project_root,
            extension_root=extension_root,
        )
        self._registry = registry
        self._artifacts = artifacts
        self._resolver = resolver or RequirementResolver()
        self._store = store or ObservationStore()

    def validate_local(
        self,
        request: StrategyExtensionValidationRequest,
    ) -> OperationOutcome:
        try:
            loaded = self._module_loader.load(
                request.module_path,
                module_prefix="_qlibx_local_strategy",
            )
        except Exception as exc:
            return self._failure(
                request,
                stage_path=f"{self.operation}.module",
                code="STRATEGY_EXTENSION_MODULE_INVALID",
                exception=exc,
                retry=("fix the local module path or import failure and validate again",),
            )

        try:
            contract = self._module_contract(loaded, request.strategy_id)
        except _ContractError as exc:
            return self._failure(
                request,
                stage_path=f"{self.operation}.contract",
                code=exc.code,
                exception=exc,
                context=exc.context,
                retry=("fix the fixed Strategy module contract and validate again",),
            )
        except Exception as exc:
            return self._failure(
                request,
                stage_path=f"{self.operation}.contract",
                code="STRATEGY_EXTENSION_CONTRACT_INVALID",
                exception=exc,
                retry=("fix the fixed Strategy module contract and validate again",),
            )

        resolution = self._resolver.resolve(
            operation=self.operation,
            idempotency_identity=request.invocation_id,
            requirements=contract.dataset_requirements,
            registry=self._registry,
        )
        if resolution.failed:
            return self._publish_errors(resolution.errors)

        artifact_resolution = StrategyArtifactResolver().resolve(
            operation=self.operation,
            invocation_id=request.invocation_id,
            requirements=contract.artifact_requirements,
            bindings=request.artifact_bindings,
            artifacts=self._artifacts,
            contract_registry=contract.artifact_contracts,
        )
        if artifact_resolution.failed:
            return self._publish_errors(artifact_resolution.errors)

        try:
            fixture = self._fixture_state(request, contract.spec.strategy_id)
        except Exception as exc:
            return self._failure(
                request,
                stage_path=f"{self.operation}.fixture",
                code="STRATEGY_EXTENSION_FIXTURE_UNAVAILABLE",
                exception=exc,
                retry=("provide compatible frozen checkpoint or performance evidence",),
            )

        first_projections = tuple(
            projection.model_copy(deep=True)
            for projection in artifact_resolution.projections
        )
        second_projections = tuple(
            projection.model_copy(deep=True)
            for projection in artifact_resolution.projections
        )
        first_view = self._strategy_view(
            request,
            resolution.bindings,
            first_projections,
            fixture,
        )
        second_view = self._strategy_view(
            request,
            resolution.bindings,
            second_projections,
            fixture,
        )
        try:
            first_draft = contract.first.run(first_view)
            if not isinstance(first_draft, StrategyDraft):
                raise TypeError("Strategy run must return StrategyDraft")
            second_draft = contract.second.run(second_view)
            if not isinstance(second_draft, StrategyDraft):
                raise TypeError("Strategy run must return StrategyDraft")
        except ArtifactViewAccessError as exc:
            return self._failure(
                request,
                stage_path=f"{self.operation}.fixture.access",
                code=exc.error_code,
                exception=exc,
                context=exc.context,
                retry=("correct the declared artifact role or requested payload type",),
            )
        except ViewAccessError as exc:
            return self._failure(
                request,
                stage_path=f"{self.operation}.fixture.access",
                code="STRATEGY_EXTENSION_VALIDATION_FAILED",
                exception=exc,
                retry=("declare or provide every Strategy view input used by the fixture",),
            )
        except Exception as exc:
            return self._failure(
                request,
                stage_path=f"{self.operation}.fixture.compute",
                code="STRATEGY_EXTENSION_VALIDATION_FAILED",
                exception=exc,
                retry=("correct the Strategy output or computation and validate again",),
            )

        first_evidence = self._view_evidence(first_view)
        second_evidence = self._view_evidence(second_view)
        if first_draft != second_draft or first_evidence != second_evidence:
            return self._failure(
                request,
                stage_path=f"{self.operation}.determinism",
                code="STRATEGY_EXTENSION_NONDETERMINISTIC",
                exception=ValueError(
                    "fresh Strategy instances produced different drafts or access evidence"
                ),
                context={
                    "first_output_hash": self._model_hash(first_draft),
                    "second_output_hash": self._model_hash(second_draft),
                    "access_evidence_equal": first_evidence == second_evidence,
                },
                retry=("remove hidden mutable, random, or wall-clock-dependent behavior",),
            )

        validation_fingerprint = self._validation_fingerprint(request, contract)
        registration = StrategyExtensionRegistration(
            strategy_id=contract.spec.strategy_id,
            module_path=contract.loaded.project_relative_path,
            source_hash=contract.loaded.source_hash,
            producer_id=f"project-local.strategy.{contract.spec.strategy_id}",
            spec=contract.spec,
            dataset_requirements=contract.dataset_requirements,
            artifact_requirements=contract.artifact_requirements,
            artifact_bindings=request.artifact_bindings,
            artifact_models=contract.artifact_models,
            evaluation_time=request.evaluation_time,
            config_fingerprint=request.config_fingerprint,
            account_checkpoint_artifact_id=request.account_checkpoint_artifact_id,
            session_performance_artifact_id=request.session_performance_artifact_id,
            validation_fingerprint=validation_fingerprint,
            validation_output_hash=self._model_hash(first_draft),
            validation_output=first_draft,
            accesses=first_view.accessed(),
            artifact_accesses=first_view.artifact_accessed(),
            state_accesses=first_view.state_accessed(),
            feedback_accesses=first_view.feedback_accessed(),
            performance_accesses=first_view.performance_accessed(),
            memory_accesses=first_view.memory_accessed(),
        )
        publication = self._artifacts.publish_model(
            logical_identity=(
                f"strategy-extension-registration:{registration.strategy_id}:"
                f"{registration.source_hash}:{validation_fingerprint}"
            ),
            artifact_type=STRATEGY_EXTENSION_REGISTRATION_CONTRACT.artifact_type,
            artifact_schema_version=(
                STRATEGY_EXTENSION_REGISTRATION_CONTRACT.artifact_schema_version
            ),
            producer_id=registration.producer_id,
            payload=registration,
            dependencies=self._registration_dependencies(registration),
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            return publication
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=StrategyExtensionValidationResult(
                registration_artifact_id=publication.result.artifact_id,
                registration=registration,
            ),
            diagnostics=(publication.result,),
        )

    def registered(self) -> tuple[RegisteredStrategyExtension, ...]:
        values: list[RegisteredStrategyExtension] = []
        for envelope in self._artifacts.list_envelopes(
            artifact_type=STRATEGY_EXTENSION_REGISTRATION_CONTRACT.artifact_type
        ):
            if envelope.artifact_type != STRATEGY_EXTENSION_REGISTRATION_CONTRACT.artifact_type:
                continue
            loaded = self._artifacts.load_model(
                envelope.artifact_id,
                STRATEGY_EXTENSION_REGISTRATION_CONTRACT,
            )
            if loaded.status is OutcomeStatus.COMPLETE:
                values.append(
                    RegisteredStrategyExtension(
                        registration_artifact_id=envelope.artifact_id,
                        registration=loaded.result.payload,
                    )
                )
        return tuple(sorted(values, key=lambda item: item.registration_artifact_id))

    def load_registered(self, registration_artifact_id: str) -> OperationOutcome:
        """Load only the exact registration selected by the caller."""

        loaded_registration = self._artifacts.load_model(
            registration_artifact_id,
            STRATEGY_EXTENSION_REGISTRATION_CONTRACT,
        )
        if loaded_registration.status is not OutcomeStatus.COMPLETE:
            return self._registered_failure(
                registration_artifact_id,
                stage_path="strategy_extension.load.registration",
                code="STRATEGY_EXTENSION_REGISTRATION_INVALID",
                exception=ValueError(
                    "registration artifact is missing, failed, or contract-incompatible"
                ),
                retry=("select an exact successful Strategy registration artifact ID",),
            )
        registration = loaded_registration.result.payload
        try:
            current_source_hash = self._module_loader.registered_source_hash(
                registration.module_path
            )
        except Exception as exc:
            return self._registered_failure(
                registration_artifact_id,
                stage_path="strategy_extension.load.source",
                code="STRATEGY_EXTENSION_LOAD_FAILED",
                exception=exc,
                retry=("restore the registered module path and validate it again",),
            )
        if current_source_hash != registration.source_hash:
            return self._registered_failure(
                registration_artifact_id,
                stage_path="strategy_extension.load.source",
                code="STRATEGY_EXTENSION_SOURCE_DRIFT",
                exception=ValueError("current Strategy source hash differs from registration"),
                context={
                    "expected_source_hash": registration.source_hash,
                    "actual_source_hash": current_source_hash,
                    "module_path": registration.module_path,
                },
                retry=("validate the changed source and select its new registration ID",),
            )
        try:
            loaded_module = self._module_loader.load_registered(
                registration.module_path,
                module_prefix="_qlibx_registered_strategy",
                expected_source_hash=registration.source_hash,
            )
        except LocalModuleSourceDriftError as exc:
            return self._registered_failure(
                registration_artifact_id,
                stage_path="strategy_extension.load.source",
                code="STRATEGY_EXTENSION_SOURCE_DRIFT",
                exception=exc,
                context={
                    "expected_source_hash": exc.expected_source_hash,
                    "actual_source_hash": exc.actual_source_hash,
                    "module_path": registration.module_path,
                },
                retry=("validate the changed source and select its new registration ID",),
            )
        except Exception as exc:
            return self._registered_failure(
                registration_artifact_id,
                stage_path="strategy_extension.load.contract",
                code="STRATEGY_EXTENSION_LOAD_FAILED",
                exception=exc,
                retry=("restore dependencies or validate the Strategy module again",),
            )
        try:
            contract = self._module_contract(loaded_module, registration.strategy_id)
        except Exception as exc:
            return self._registered_failure(
                registration_artifact_id,
                stage_path="strategy_extension.load.contract",
                code="STRATEGY_EXTENSION_LOAD_FAILED",
                exception=exc,
                retry=("restore dependencies or validate the Strategy module again",),
            )
        expected_contract = (
            registration.spec,
            registration.dataset_requirements,
            registration.artifact_requirements,
            registration.artifact_models,
        )
        actual_contract = (
            contract.spec,
            contract.dataset_requirements,
            contract.artifact_requirements,
            contract.artifact_models,
        )
        if actual_contract != expected_contract:
            return self._registered_failure(
                registration_artifact_id,
                stage_path="strategy_extension.load.contract",
                code="STRATEGY_EXTENSION_CONTRACT_DRIFT",
                exception=ValueError(
                    "current Strategy declaration or payload schema differs from registration"
                ),
                context={
                    "strategy_id": registration.strategy_id,
                    "module_path": registration.module_path,
                },
                retry=("validate the changed contract and select its new registration ID",),
            )
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=LoadedStrategyExtension(
                registration_artifact_id=registration_artifact_id,
                registration=registration,
                operation=contract.first,
                artifact_contracts=contract.artifact_contracts,
            ),
            diagnostics=(loaded_registration.result.envelope,),
        )

    def _module_contract(
        self,
        loaded: LoadedLocalModule,
        expected_strategy_id: str,
    ) -> _ModuleContract:
        module = loaded.module
        try:
            spec = StrategyExtensionSpec.model_validate(module.STRATEGY_SPEC)
        except Exception as exc:
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                f"invalid STRATEGY_SPEC: {exc}",
            ) from exc
        if spec.strategy_id != expected_strategy_id:
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                "request strategy_id does not match STRATEGY_SPEC",
                {
                    "expected_strategy_id": expected_strategy_id,
                    "actual_strategy_id": spec.strategy_id,
                },
            )
        factory = getattr(module, "create_strategy", None)
        if not callable(factory):
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                "create_strategy must be callable",
            )
        try:
            if inspect.signature(factory).parameters:
                raise _ContractError(
                    "STRATEGY_EXTENSION_CONTRACT_INVALID",
                    "create_strategy must accept no arguments",
                )
        except TypeError as exc:
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                "create_strategy must expose an inspectable zero-argument signature",
            ) from exc
        first = factory()
        second = factory()
        if first is second:
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                "create_strategy must return a fresh instance",
            )
        self._validate_operation(first, spec.strategy_id)
        self._validate_operation(second, spec.strategy_id)
        first_requirements = self._dataset_requirements(first)
        second_requirements = self._dataset_requirements(second)
        first_artifacts = self._artifact_requirements(first)
        second_artifacts = self._artifact_requirements(second)
        if first_requirements != second_requirements or first_artifacts != second_artifacts:
            raise _ContractError(
                "STRATEGY_EXTENSION_NONDETERMINISTIC",
                "fresh Strategy instances declared different requirements",
            )
        model_registrations, custom_contracts = self._artifact_models(module, spec)
        try:
            contract_registry = StrategyArtifactContractRegistry.built_in().extended(
                custom_contracts
            )
        except ValueError as exc:
            raise _ContractError(
                "STRATEGY_EXTENSION_ARTIFACT_MODEL_INVALID",
                str(exc),
            ) from exc
        return _ModuleContract(
            loaded=loaded,
            spec=spec,
            first=first,
            second=second,
            dataset_requirements=first_requirements,
            artifact_requirements=first_artifacts,
            artifact_models=model_registrations,
            artifact_contracts=contract_registry,
        )

    @staticmethod
    def _validate_operation(operation: object, strategy_id: str) -> None:
        if getattr(operation, "strategy_id", None) != strategy_id:
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                "created Strategy identity does not match STRATEGY_SPEC",
            )
        if not callable(getattr(operation, "requirements", None)):
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                "Strategy requirements must be callable",
            )
        if not callable(getattr(operation, "run", None)):
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                "Strategy run must be callable",
            )
        artifact_method = getattr(operation, "artifact_requirements", None)
        if artifact_method is not None and not callable(artifact_method):
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                "artifact_requirements must be callable when present",
            )

    @staticmethod
    def _dataset_requirements(
        operation: StrategyOperation,
    ) -> tuple[ComponentRequirement, ...]:
        try:
            requirements = tuple(operation.requirements())
        except Exception as exc:
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                f"Strategy requirements failed: {exc}",
            ) from exc
        if not all(isinstance(item, ComponentRequirement) for item in requirements):
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                "requirements must contain ComponentRequirement values",
            )
        StrategyExtensionFlow._validate_unique_requirements(
            tuple(item.requirement_id for item in requirements),
            tuple(item.semantic_role for item in requirements),
            "dataset",
        )
        return requirements

    @staticmethod
    def _artifact_requirements(
        operation: StrategyOperation,
    ) -> tuple[StrategyArtifactRequirement, ...]:
        method = getattr(operation, "artifact_requirements", None)
        if method is None:
            return ()
        try:
            requirements = tuple(method())
        except Exception as exc:
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                f"Strategy artifact requirements failed: {exc}",
            ) from exc
        if not all(isinstance(item, StrategyArtifactRequirement) for item in requirements):
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                "artifact_requirements must contain StrategyArtifactRequirement values",
            )
        StrategyExtensionFlow._validate_unique_requirements(
            tuple(item.requirement_id for item in requirements),
            tuple(item.consumer_role for item in requirements),
            "artifact",
        )
        return requirements

    @staticmethod
    def _validate_unique_requirements(
        ids: tuple[str, ...],
        roles: tuple[str, ...],
        kind: str,
    ) -> None:
        if len(ids) != len(set(ids)):
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                f"{kind} requirement IDs must be unique",
            )
        if len(roles) != len(set(roles)):
            raise _ContractError(
                "STRATEGY_EXTENSION_CONTRACT_INVALID",
                f"{kind} requirement roles must be unique",
            )

    @staticmethod
    def _artifact_models(
        module: ModuleType,
        spec: StrategyExtensionSpec,
    ) -> tuple[tuple[StrategyArtifactModelRegistration, ...], tuple[ArtifactContract, ...]]:
        registrations: list[StrategyArtifactModelRegistration] = []
        contracts: list[ArtifactContract] = []
        for selected in spec.artifact_models:
            model = getattr(module, selected.model_symbol, None)
            if not isinstance(model, type) or not issubclass(model, QlibxModel):
                raise _ContractError(
                    "STRATEGY_EXTENSION_ARTIFACT_MODEL_INVALID",
                    f"{selected.model_symbol} must be a module-local QlibxModel subclass",
                )
            if model.__module__ != module.__name__:
                raise _ContractError(
                    "STRATEGY_EXTENSION_ARTIFACT_MODEL_INVALID",
                    f"{selected.model_symbol} must be defined in the Strategy module",
                )
            try:
                schema = json.dumps(
                    model.model_json_schema(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            except Exception as exc:
                raise _ContractError(
                    "STRATEGY_EXTENSION_ARTIFACT_MODEL_INVALID",
                    f"cannot materialize JSON schema for {selected.model_symbol}: {exc}",
                ) from exc
            schema_hash = hashlib.sha256(schema.encode()).hexdigest()
            registrations.append(
                StrategyArtifactModelRegistration(
                    artifact_type=selected.artifact_type,
                    artifact_schema_version=selected.artifact_schema_version,
                    model_symbol=selected.model_symbol,
                    json_schema_hash=schema_hash,
                )
            )
            contracts.append(
                ArtifactContract(
                    artifact_type=selected.artifact_type,
                    artifact_schema_version=selected.artifact_schema_version,
                    payload_model=model,
                )
            )
        return tuple(registrations), tuple(contracts)

    def _fixture_state(
        self,
        request: StrategyExtensionValidationRequest,
        strategy_id: str,
    ) -> _FixtureState:
        account_state = None
        account_feedback = None
        memory_state = None
        if request.account_checkpoint_artifact_id is not None:
            loaded = self._artifacts.load_model(
                request.account_checkpoint_artifact_id,
                SIMULATION_CHECKPOINT_CONTRACT,
            )
            if loaded.status is not OutcomeStatus.COMPLETE:
                raise ValueError("account checkpoint artifact is missing or incompatible")
            checkpoint = loaded.result.payload
            if checkpoint.event_time > request.evaluation_time:
                raise ValueError("account checkpoint is later than validation evaluation_time")
            account = Account.from_checkpoint(checkpoint.account_checkpoint)
            account_state = account.snapshot(evaluation_time=request.evaluation_time)
            memory_store = StrategyMemoryStore.from_checkpoint(checkpoint.memory_snapshots)
            memory_state = memory_store.snapshot(strategy_id)
            account_feedback = account.feedback(
                memory_state.feedback_cursor,
                request.feedback_entry_limit,
            )

        session_performance = None
        if request.session_performance_artifact_id is not None:
            loaded = self._artifacts.load_model(
                request.session_performance_artifact_id,
                SESSION_PERFORMANCE_CONTRACT,
            )
            if loaded.status is not OutcomeStatus.COMPLETE:
                raise ValueError("session performance artifact is missing or incompatible")
            record = loaded.result.payload
            if record.event_time > request.evaluation_time:
                raise ValueError("session performance is later than validation evaluation_time")
            if account_state is not None and record.account_id != account_state.account_id:
                raise ValueError("session performance account does not match checkpoint Account")
            session_performance = _PublishedPerformance(
                artifact_id=loaded.result.envelope.artifact_id,
                record=record,
            )
        return _FixtureState(
            account_state=account_state,
            account_feedback=account_feedback,
            memory_state=memory_state,
            session_performance=session_performance,
        )

    def _strategy_view(
        self,
        request: StrategyExtensionValidationRequest,
        bindings: tuple[ResolvedBinding, ...],
        artifact_inputs: tuple[ArtifactInputProjection, ...],
        fixture: _FixtureState,
    ) -> StrategyView:
        return ViewGate(self._registry, self._store).strategy_view(
            BacktestClock(request.evaluation_time),
            bindings,
            account_state=fixture.account_state,
            account_feedback=fixture.account_feedback,
            session_performance=fixture.session_performance,
            memory_state=fixture.memory_state,
            artifact_inputs=artifact_inputs,
        )

    @staticmethod
    def _view_evidence(view: StrategyView) -> tuple[object, ...]:
        return (
            view.accessed(),
            view.artifact_accessed(),
            view.state_accessed(),
            view.feedback_accessed(),
            view.performance_accessed(),
            view.memory_accessed(),
        )

    @staticmethod
    def _registration_dependencies(
        registration: StrategyExtensionRegistration,
    ) -> tuple[DependencyEdge, ...]:
        dependencies: list[DependencyEdge] = [
            DependencyEdge(
                dependency_kind="config",
                dependency_id=registration.config_fingerprint,
                consumer_role="strategy_extension_validation_config",
            ),
            DependencyEdge(
                dependency_kind="config",
                dependency_id=registration.source_hash,
                consumer_role="strategy_extension_source",
            ),
        ]
        dependencies.extend(
            DependencyEdge(
                dependency_kind="dataset",
                dependency_id=access.registration_identity,
                consumer_role=access.semantic_role,
                selected_fields=(access.selected_field,),
            )
            for access in registration.accesses
        )
        dependencies.extend(
            DependencyEdge(
                dependency_kind="artifact",
                dependency_id=access.artifact_id,
                consumer_role=access.consumer_role,
                compatibility_fingerprint=access.content_hash,
            )
            for access in registration.artifact_accesses
        )
        if registration.account_checkpoint_artifact_id is not None and (
            registration.state_accesses
            or registration.feedback_accesses
            or registration.memory_accesses
        ):
            dependencies.append(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=registration.account_checkpoint_artifact_id,
                    consumer_role="strategy_validation_checkpoint",
                )
            )
        if registration.session_performance_artifact_id is not None and (
            registration.performance_accesses
        ):
            dependencies.append(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=registration.session_performance_artifact_id,
                    consumer_role="strategy_validation_session_performance",
                )
            )
        return tuple(dependencies)

    @staticmethod
    def _validation_fingerprint(
        request: StrategyExtensionValidationRequest,
        contract: _ModuleContract,
    ) -> str:
        payload = {
            "request": request.model_dump(mode="json"),
            "source_hash": contract.loaded.source_hash,
            "dataset_requirements": [
                item.model_dump(mode="json") for item in contract.dataset_requirements
            ],
            "artifact_requirements": [
                item.model_dump(mode="json") for item in contract.artifact_requirements
            ],
            "artifact_models": [
                item.model_dump(mode="json") for item in contract.artifact_models
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _model_hash(model: QlibxModel) -> str:
        return hashlib.sha256(model.model_dump_json().encode()).hexdigest()

    def _publish_errors(self, errors: tuple[OperationError, ...]) -> OperationOutcome:
        return publish_failed_errors(self._artifacts, errors)

    def _registered_failure(
        self,
        registration_artifact_id: str,
        *,
        stage_path: str,
        code: str,
        exception: Exception,
        retry: tuple[str, ...],
        context: dict[str, object] | None = None,
    ) -> OperationOutcome:
        error = build_operation_error(
            operation="strategy_extension.load",
            stage_path=stage_path,
            error_code=code,
            idempotency_identity=registration_artifact_id,
            error_identity_seed=f"{registration_artifact_id}:{stage_path}:{code}",
            context={
                "registration_artifact_id": registration_artifact_id,
                "exception": type(exception).__name__,
                "message": str(exception)[:500],
                **(context or {}),
            },
            retry_preconditions=retry,
        )
        return publish_failed_outcome(self._artifacts, error)

    def _failure(
        self,
        request: StrategyExtensionValidationRequest,
        *,
        stage_path: str,
        code: str,
        exception: Exception,
        retry: tuple[str, ...],
        context: dict[str, object] | None = None,
    ) -> OperationOutcome:
        error = build_operation_error(
            operation=self.operation,
            stage_path=stage_path,
            error_code=code,
            idempotency_identity=request.invocation_id,
            error_identity_seed=f"{request.invocation_id}:{stage_path}:{code}",
            context={
                "strategy_id": request.strategy_id,
                "module_path": request.module_path,
                "exception": type(exception).__name__,
                "message": str(exception)[:500],
                **(context or {}),
            },
            retry_preconditions=retry,
        )
        return publish_failed_outcome(self._artifacts, error)