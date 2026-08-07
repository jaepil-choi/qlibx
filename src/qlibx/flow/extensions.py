"""Validation and append-only registration of project-local transforms."""

import hashlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import cast

from qlibx.context import MaterializeView, ViewGate
from qlibx.data import ObservationStore, RegistrySnapshot, RequirementResolver
from qlibx.errors import OperationOutcome, OutcomeStatus
from qlibx.evidence import ArtifactContract, DependencyEdge, LocalArtifactBackend
from qlibx.extensions import (
    ExtensionRegistration,
    ExtensionValidationRequest,
    NeutralizationExtensionSpec,
    NeutralizationInput,
    NeutralizationInputRow,
    NeutralizationResult,
)
from qlibx.extensions.local_modules import LocalModuleLoader
from qlibx.flow.failures import (
    build_operation_error,
    publish_failed_errors,
    publish_failed_outcome,
)
from qlibx.kernel import BacktestClock

EXTENSION_REGISTRATION_CONTRACT = ArtifactContract(
    artifact_type="extension_registration",
    artifact_schema_version=1,
    payload_model=ExtensionRegistration,
)

Transform = Callable[[NeutralizationInput], NeutralizationResult]


class ExtensionFlow:
    """Validate local code against frozen real inputs before catalog visibility."""

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

    def validate_local(self, request: ExtensionValidationRequest) -> OperationOutcome:
        try:
            loaded_module = self._module_loader.load(request.module_path)
            spec, transform = self._module_contract(loaded_module.module)
            if spec.extension_id != request.extension_id:
                raise ValueError("request extension_id does not match EXTENSION_SPEC")
        except Exception as exc:
            return self._failure(
                request,
                stage_path="extension.validate.module",
                code="EXTENSION_MODULE_INVALID",
                context={"exception": type(exc).__name__, "message": str(exc)[:500]},
                retry=("fix the local module contract and validate it again",),
            )

        resolution = self._resolver.resolve(
            operation="extension.validate",
            idempotency_identity=request.invocation_id,
            requirements=spec.requirements(),
            registry=self._registry,
        )
        if resolution.failed:
            return publish_failed_errors(self._artifacts, resolution.errors)

        view = ViewGate(self._registry, self._store).materialize_view(
            BacktestClock(request.evaluation_time),
            resolution.bindings,
        )
        try:
            validation_input = self._materialize_input(view, spec, request)
            first = NeutralizationResult.model_validate(transform(validation_input))
            second = NeutralizationResult.model_validate(transform(validation_input))
            self._validate_output(spec, validation_input, first, second)
        except Exception as exc:
            return self._failure(
                request,
                stage_path="extension.validate.fixture",
                code="EXTENSION_VALIDATION_FAILED",
                context={
                    "exception": type(exc).__name__,
                    "message": str(exc)[:500],
                    "accesses": [item.model_dump(mode="json") for item in view.accessed()],
                },
                retry=("correct the transform output and rerun the same validation fixture",),
            )

        registration = ExtensionRegistration(
            extension_id=spec.extension_id,
            module_path=loaded_module.project_relative_path,
            source_hash=loaded_module.source_hash,
            producer_id=f"project-local.{spec.extension_id}",
            spec=spec,
            validation_input_hash=self._model_hash(validation_input),
            validation_output_hash=self._model_hash(first),
            validation_output=first,
            evaluation_time=request.evaluation_time,
            accesses=view.accessed(),
        )
        publication = self._artifacts.publish_model(
            logical_identity=(
                f"extension-registration:{spec.extension_id}:{loaded_module.source_hash}"
            ),
            artifact_type="extension_registration",
            artifact_schema_version=1,
            producer_id=registration.producer_id,
            payload=registration,
            dependencies=(
                DependencyEdge(
                    dependency_kind="config",
                    dependency_id=request.config_fingerprint,
                    consumer_role="extension_validation_config",
                ),
                *(
                    DependencyEdge(
                        dependency_kind="dataset",
                        dependency_id=access.registration_identity,
                        consumer_role=access.semantic_role,
                        selected_fields=(access.selected_field,),
                    )
                    for access in registration.accesses
                ),
            ),
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            return publication
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=registration,
            diagnostics=(publication.result,),
        )

    def registered(self) -> tuple[ExtensionRegistration, ...]:
        registrations: list[ExtensionRegistration] = []
        for envelope in self._artifacts.list_envelopes(
            artifact_type=EXTENSION_REGISTRATION_CONTRACT.artifact_type
        ):
            if envelope.artifact_type != EXTENSION_REGISTRATION_CONTRACT.artifact_type:
                continue
            loaded = self._artifacts.load_model(
                envelope.artifact_id,
                EXTENSION_REGISTRATION_CONTRACT,
            )
            if loaded.status is OutcomeStatus.COMPLETE:
                registrations.append(loaded.result.payload)
        return tuple(sorted(registrations, key=lambda item: (item.extension_id, item.source_hash)))

    @staticmethod
    def _module_contract(module: ModuleType) -> tuple[NeutralizationExtensionSpec, Transform]:
        spec = NeutralizationExtensionSpec.model_validate(module.EXTENSION_SPEC)
        transform = module.transform
        if not callable(transform):
            raise TypeError("transform must be callable")
        return spec, cast(Transform, transform)

    @staticmethod
    def _materialize_input(
        view: MaterializeView,
        spec: NeutralizationExtensionSpec,
        request: ExtensionValidationRequest,
    ) -> NeutralizationInput:
        value_role = spec.value_requirement.semantic_role
        group_role = spec.group_requirement.semantic_role
        values = view.latest(value_role)[["instrument", value_role]]
        groups = view.latest(group_role)[["instrument", group_role]]
        merged = values.merge(groups, on="instrument", how="inner", validate="one_to_one")
        if merged.empty:
            raise ValueError("PIT-visible value and group inputs have no common instruments")
        if len(merged) != len(values) or len(merged) != len(groups):
            raise ValueError("value and group inputs must have identical instrument axes")
        merged = merged.sort_values("instrument", kind="mergesort")
        return NeutralizationInput(
            evaluation_time=request.evaluation_time,
            rows=tuple(
                NeutralizationInputRow(
                    instrument=str(row.instrument),
                    group=str(getattr(row, group_role)),
                    value=float(getattr(row, value_role)),
                )
                for row in merged.itertuples(index=False)
            ),
        )

    @staticmethod
    def _validate_output(
        spec: NeutralizationExtensionSpec,
        validation_input: NeutralizationInput,
        first: NeutralizationResult,
        second: NeutralizationResult,
    ) -> None:
        if first != second:
            raise ValueError("transform is not deterministic for the frozen validation input")
        if first.extension_id != spec.extension_id:
            raise ValueError("result extension_id does not match EXTENSION_SPEC")
        input_axis = tuple(row.instrument for row in validation_input.rows)
        output_axis = tuple(row.instrument for row in first.values)
        if output_axis != input_axis:
            raise ValueError("transform output must preserve the stable instrument axis")
        groups = {row.instrument: row.group for row in validation_input.rows}
        sums: dict[str, float] = {}
        for item in first.values:
            group = groups[item.instrument]
            sums[group] = sums.get(group, 0.0) + item.value
        if any(abs(total) > 1e-12 for total in sums.values()):
            raise ValueError("neutralized values must sum to zero within each group")

    @staticmethod
    def _model_hash(model: NeutralizationInput | NeutralizationResult) -> str:
        return hashlib.sha256(model.model_dump_json().encode()).hexdigest()

    def _failure(
        self,
        request: ExtensionValidationRequest,
        *,
        stage_path: str,
        code: str,
        context: dict[str, object],
        retry: tuple[str, ...],
    ) -> OperationOutcome:
        error = build_operation_error(
            operation="extension.validate",
            stage_path=stage_path,
            error_code=code,
            idempotency_identity=request.invocation_id,
            error_identity_seed=f"{request.invocation_id}:{stage_path}:{code}",
            context=context,
            retry_preconditions=retry,
        )
        return publish_failed_outcome(self._artifacts, error)
