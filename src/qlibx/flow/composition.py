"""Producer-independent stored Strategy composition."""

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from qlibx.data import ComponentRequirement, RegistrySnapshot
from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus
from qlibx.evidence import (
    ArtifactContract,
    ArtifactEnvelope,
    DependencyEdge,
    LoadedArtifact,
    LocalArtifactBackend,
)
from qlibx.flow.research import ResearchFlow, StrategyRunResult
from qlibx.models import QlibxModel
from qlibx.operations import (
    BudgetMode,
    DecisionAction,
    StrategyDraft,
    StrategyInvocation,
    StrategyResult,
    WeightEntry,
)

STRATEGY_RESULT_CONTRACT = ArtifactContract(
    artifact_type="strategy_result",
    artifact_schema_version=1,
    payload_model=StrategyResult,
)


class StoredSignalEntry(QlibxModel):
    instrument: str = Field(min_length=1)
    value: float


class StoredSignalResult(QlibxModel):
    signal_schema_version: int = 1
    signal_semantics: str = Field(min_length=1)
    observation_time: datetime
    entries: tuple[StoredSignalEntry, ...]

    @model_validator(mode="after")
    def validate_entries(self) -> "StoredSignalResult":
        instruments = [entry.instrument for entry in self.entries]
        if not instruments or len(instruments) != len(set(instruments)):
            raise ValueError("stored signal requires unique instrument entries")
        return self


STORED_SIGNAL_CONTRACT = ArtifactContract(
    artifact_type="stored_signal_result",
    artifact_schema_version=1,
    payload_model=StoredSignalResult,
)


class StoredSignalWeighting(StrEnum):
    LONG_SHORT_EXTREMES = "long_short_extremes"
    LONG_ONLY_MAX = "long_only_max"


class EnsembleMemberSpec(QlibxModel):
    artifact_id: str = Field(min_length=1)
    allocation: float = Field(gt=0)


class EnsembleDefinition(QlibxModel):
    strategy_id: str = Field(min_length=1)
    members: tuple[EnsembleMemberSpec, ...]
    budget_mode: BudgetMode
    target_gross: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_members(self) -> "EnsembleDefinition":
        identities = [member.artifact_id for member in self.members]
        if not identities:
            raise ValueError("ensemble requires at least one stored member")
        if len(identities) != len(set(identities)):
            raise ValueError("ensemble member artifact IDs must be unique")
        return self


class MemberContribution(QlibxModel):
    instrument: str
    member_artifact_id: str
    member_strategy_id: str
    member_weight: float
    allocation: float
    contribution: float


class EnsembleEvidence(QlibxModel):
    ensemble_schema_version: int = 1
    invocation_id: str
    strategy_id: str
    result_artifact_id: str
    contributions: tuple[MemberContribution, ...]
    gross_before_netting: float
    gross_after_netting: float
    net_exposure: float
    crossed_gross: float
    residual_budget: float
    member_state_identities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EnsembleRunResult:
    strategy: StrategyRunResult
    evidence: EnsembleEvidence
    evidence_artifact: ArtifactEnvelope


class EnsembleCompatibilityError(ValueError):
    def __init__(self, code: str, context: dict[str, object]) -> None:
        super().__init__(code)
        self.code = code
        self.context = context


@dataclass(frozen=True, slots=True)
class _StoredMember:
    spec: EnsembleMemberSpec
    loaded: LoadedArtifact[StrategyResult]


class EnsembleStrategyOperation:
    """Pure Strategy operation over already-loaded immutable member results."""

    def __init__(
        self,
        definition: EnsembleDefinition,
        members: tuple[_StoredMember, ...],
    ) -> None:
        self.strategy_id = definition.strategy_id
        self._definition = definition
        self._members = members
        self._contributions: tuple[MemberContribution, ...] = ()
        self._gross_before = 0.0
        self._gross_after = 0.0
        self._net = 0.0
        self._state_identities: tuple[str, ...] = ()
        self._validate_state_compatibility()

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return ()

    def run(self, view: object) -> StrategyDraft:
        del view
        contributions = tuple(
            MemberContribution(
                instrument=weight.instrument,
                member_artifact_id=member.loaded.envelope.artifact_id,
                member_strategy_id=member.loaded.payload.strategy_id,
                member_weight=weight.weight,
                allocation=member.spec.allocation,
                contribution=weight.weight * member.spec.allocation,
            )
            for member in self._members
            for weight in member.loaded.payload.weights
        )
        netted: dict[str, float] = {}
        for item in contributions:
            netted[item.instrument] = netted.get(item.instrument, 0) + item.contribution
        weights = tuple(
            WeightEntry(instrument=instrument, weight=weight)
            for instrument, weight in sorted(netted.items())
            if abs(weight) > 1e-15
        )
        gross_before = sum(abs(item.contribution) for item in contributions)
        gross_after = sum(abs(item.weight) for item in weights)
        if gross_after > self._definition.target_gross + 1e-10:
            raise EnsembleCompatibilityError(
                "ENSEMBLE_GROSS_EXCEEDS_TARGET",
                {
                    "gross_after_netting": gross_after,
                    "target_gross": self._definition.target_gross,
                },
            )
        if (
            self._definition.budget_mode is BudgetMode.FIXED
            and not math.isclose(
                gross_after,
                self._definition.target_gross,
                abs_tol=1e-10,
            )
        ):
            raise EnsembleCompatibilityError(
                "ENSEMBLE_FIXED_BUDGET_INCOMPATIBLE",
                {
                    "gross_after_netting": gross_after,
                    "target_gross": self._definition.target_gross,
                },
            )
        self._contributions = contributions
        self._gross_before = gross_before
        self._gross_after = gross_after
        self._net = sum(item.weight for item in weights)
        state_identity = self._state_identities[0] if self._state_identities else None
        cursor = next(
            (
                member.loaded.payload.feedback_cursor
                for member in self._members
                if member.loaded.payload.path_dependent
            ),
            None,
        )
        return StrategyDraft(
            weights=weights,
            budget_mode=self._definition.budget_mode,
            target_gross=self._definition.target_gross,
            decision_action=DecisionAction.TARGET,
            diagnostics=(
                f"member_gross={gross_before:.12g}",
                f"crossed_gross={gross_before - gross_after:.12g}",
            ),
            path_dependent=bool(self._state_identities),
            state_identity=state_identity,
            feedback_cursor=cursor,
        )

    def evidence(
        self,
        invocation: StrategyInvocation,
        result_artifact_id: str,
    ) -> EnsembleEvidence:
        return EnsembleEvidence(
            invocation_id=invocation.invocation_id,
            strategy_id=self.strategy_id,
            result_artifact_id=result_artifact_id,
            contributions=self._contributions,
            gross_before_netting=self._gross_before,
            gross_after_netting=self._gross_after,
            net_exposure=self._net,
            crossed_gross=self._gross_before - self._gross_after,
            residual_budget=self._definition.target_gross - self._gross_after,
            member_state_identities=self._state_identities,
        )

    def _validate_state_compatibility(self) -> None:
        path_members = tuple(
            member.loaded.payload
            for member in self._members
            if member.loaded.payload.path_dependent
        )
        identities = tuple(
            sorted(
                {
                    (
                        f"{member.state_identity}:cursor={member.feedback_cursor}:"
                        + ",".join(
                            f"{state.account_id}:v{state.version}:c{state.feedback_cursor}"
                            for state in member.state_accesses
                        )
                    )
                    for member in path_members
                }
            )
        )
        if len(identities) > 1:
            raise EnsembleCompatibilityError(
                "ENSEMBLE_STATE_INCOMPATIBLE",
                {"member_state_identities": list(identities)},
            )
        self._state_identities = identities


class StoredSignalStrategyOperation:
    """Build weights from a loaded characteristic without its producer implementation."""

    def __init__(
        self,
        *,
        strategy_id: str,
        signal: StoredSignalResult,
        weighting: StoredSignalWeighting,
    ) -> None:
        self.strategy_id = strategy_id
        self._signal = signal
        self._weighting = weighting

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return ()

    def run(self, view: object) -> StrategyDraft:
        del view
        ordered = sorted(
            self._signal.entries,
            key=lambda entry: (entry.value, entry.instrument),
        )
        if self._weighting is StoredSignalWeighting.LONG_ONLY_MAX:
            weights = (WeightEntry(instrument=ordered[-1].instrument, weight=1.0),)
        else:
            if len(ordered) < 2:
                raise ValueError("long-short weighting requires at least two instruments")
            weights = (
                WeightEntry(instrument=ordered[0].instrument, weight=-0.5),
                WeightEntry(instrument=ordered[-1].instrument, weight=0.5),
            )
        return StrategyDraft(
            weights=weights,
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
            diagnostics=(
                f"stored_signal_semantics={self._signal.signal_semantics}",
                f"weighting={self._weighting.value}",
            ),
        )


class CompositionFlow:
    """Load stored results, combine them, and publish full parent lineage."""

    def __init__(
        self,
        *,
        registry: RegistrySnapshot,
        artifacts: LocalArtifactBackend,
    ) -> None:
        self._artifacts = artifacts
        self._research = ResearchFlow(registry=registry, artifacts=artifacts)

    def invoke_ensemble(
        self,
        definition: EnsembleDefinition,
        invocation: StrategyInvocation,
    ) -> OperationOutcome:
        members: list[_StoredMember] = []
        for spec in definition.members:
            loaded = self._artifacts.load_model(
                spec.artifact_id,
                STRATEGY_RESULT_CONTRACT,
            )
            if loaded.status is not OutcomeStatus.COMPLETE:
                return loaded
            members.append(_StoredMember(spec=spec, loaded=loaded.result))
        try:
            operation = EnsembleStrategyOperation(definition, tuple(members))
            operation.run(object())
        except EnsembleCompatibilityError as exc:
            return self._failure(invocation, exc.code, exc.context)
        dependencies = tuple(
            DependencyEdge(
                dependency_kind="artifact",
                dependency_id=member.loaded.envelope.artifact_id,
                consumer_role="ensemble_member",
            )
            for member in members
        )
        combined = self._research.invoke_strategy(
            operation,
            invocation,
            additional_dependencies=dependencies,
        )
        if combined.status is not OutcomeStatus.COMPLETE:
            return combined
        strategy = combined.result
        if not isinstance(strategy, StrategyRunResult):
            return self._failure(invocation, "ENSEMBLE_RESULT_INVALID", {})
        evidence = operation.evidence(invocation, strategy.artifact.artifact_id)
        publication = self._artifacts.publish_model(
            logical_identity=f"ensemble-evidence:{invocation.invocation_id}",
            artifact_type="ensemble_evidence",
            artifact_schema_version=1,
            producer_id=definition.strategy_id,
            payload=evidence,
            dependencies=(
                *dependencies,
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=strategy.artifact.artifact_id,
                    consumer_role="ensemble_strategy_result",
                ),
            ),
        )
        if publication.status is not OutcomeStatus.COMPLETE:
            return publication
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=EnsembleRunResult(
                strategy=strategy,
                evidence=evidence,
                evidence_artifact=publication.result,
            ),
        )

    def invoke_stored_signal_strategy(
        self,
        *,
        artifact_id: str,
        strategy_id: str,
        weighting: StoredSignalWeighting,
        invocation: StrategyInvocation,
    ) -> OperationOutcome:
        loaded = self._artifacts.load_model(artifact_id, STORED_SIGNAL_CONTRACT)
        if loaded.status is not OutcomeStatus.COMPLETE:
            return loaded
        operation = StoredSignalStrategyOperation(
            strategy_id=strategy_id,
            signal=loaded.result.payload,
            weighting=weighting,
        )
        return self._research.invoke_strategy(
            operation,
            invocation,
            additional_dependencies=(
                DependencyEdge(
                    dependency_kind="artifact",
                    dependency_id=loaded.result.envelope.artifact_id,
                    consumer_role="stored_signal",
                ),
            ),
        )

    def _failure(
        self,
        invocation: StrategyInvocation,
        code: str,
        context: dict[str, object],
    ) -> OperationOutcome:
        seed = hashlib.sha256(
            f"{invocation.invocation_id}:{code}".encode()
        ).hexdigest()[:24]
        error = OperationError(
            operation="ensemble.run",
            stage_path="ensemble.run.compatibility",
            error_code=code,
            context=context,
            commit_status=CommitStatus.NONE,
            retry_preconditions=("select compatible stored member results or a flexible budget",),
            idempotency_identity=invocation.invocation_id,
            error_id=f"error-{seed}",
        )
        self._artifacts.publish_failure(error)
        return OperationOutcome(status=OutcomeStatus.FAILED, errors=(error,))
