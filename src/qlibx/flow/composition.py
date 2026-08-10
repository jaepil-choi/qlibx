"""Producer-independent stored Strategy composition."""

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from qlibx.data import ComponentRequirement, RegistrySnapshot
from qlibx.errors import OperationOutcome, OutcomeStatus
from qlibx.evidence import ArtifactEnvelope, DependencyEdge, LocalArtifactBackend
from qlibx.flow.artifact_inputs import STORED_SIGNAL_CONTRACT
from qlibx.flow.failures import build_operation_error, publish_failed_outcome
from qlibx.flow.research import ResearchFlow, StrategyRunResult
from qlibx.flow.strategy_results import (
    STRATEGY_RESULT_CONTRACT as STRATEGY_RESULT_CONTRACT,
)
from qlibx.models import QlibxModel
from qlibx.operations import (
    BudgetMode,
    DecisionAction,
    StoredSignalResult,
    StrategyArtifactBinding,
    StrategyArtifactRequirement,
    StrategyComputationError,
    StrategyDraft,
    StrategyInvocation,
    StrategyResult,
    WeightEntry,
)
from qlibx.operations import StoredSignalEntry as StoredSignalEntry
from qlibx.view import StrategyView


class StoredSignalWeighting(StrEnum):
    LONG_SHORT_EXTREMES = "long_short_extremes"
    LONG_ONLY_MAX = "long_only_max"


class EnsembleMemberSpec(QlibxModel):
    artifact_id: str = Field(min_length=1)
    allocation: float = Field(gt=0)
    artifact_schema_version: Literal[3] = 3


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


class EnsembleDraft(StrategyDraft):
    member_artifact_ids: tuple[str, ...]
    contributions: tuple[MemberContribution, ...]
    gross_before_netting: float
    gross_after_netting: float
    net_exposure: float
    crossed_gross: float
    residual_budget: float


class EnsembleEvidence(QlibxModel):
    ensemble_schema_version: Literal[2] = 2
    invocation_id: str
    strategy_id: str
    result_artifact_id: str
    member_artifact_ids: tuple[str, ...]
    contributions: tuple[MemberContribution, ...]
    gross_before_netting: float
    gross_after_netting: float
    net_exposure: float
    crossed_gross: float
    residual_budget: float


@dataclass(frozen=True, slots=True)
class EnsembleRunResult:
    strategy: StrategyRunResult
    evidence: EnsembleEvidence
    evidence_artifact: ArtifactEnvelope


class EnsembleCompatibilityError(StrategyComputationError):
    """Raised when typed member inputs cannot satisfy the Ensemble budget contract."""


class EnsembleStrategyOperation:
    """Pure Strategy operation over typed frozen member-result inputs."""

    def __init__(self, definition: EnsembleDefinition) -> None:
        self.strategy_id = definition.strategy_id
        self._definition = definition

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return ()

    def artifact_requirements(self) -> tuple[StrategyArtifactRequirement, ...]:
        return tuple(
            StrategyArtifactRequirement(
                requirement_id=self._requirement_id(index),
                consumer_role=self._consumer_role(index),
                artifact_type="strategy_result",
                artifact_schema_version=member.artifact_schema_version,
            )
            for index, member in enumerate(self._definition.members)
        )

    def run(self, view: StrategyView) -> EnsembleDraft:
        members = tuple(
            (
                member,
                view.artifact(
                    self._consumer_role(index),
                    StrategyResult,
                ),
            )
            for index, member in enumerate(self._definition.members)
        )
        contributions = tuple(
            MemberContribution(
                instrument=weight.instrument,
                member_artifact_id=member.artifact_id,
                member_strategy_id=payload.strategy_id,
                member_weight=weight.weight,
                allocation=member.allocation,
                contribution=weight.weight * member.allocation,
            )
            for member, payload in members
            for weight in payload.weights
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
        if self._definition.budget_mode is BudgetMode.FIXED and not math.isclose(
            gross_after,
            self._definition.target_gross,
            abs_tol=1e-10,
        ):
            raise EnsembleCompatibilityError(
                "ENSEMBLE_FIXED_BUDGET_INCOMPATIBLE",
                {
                    "gross_after_netting": gross_after,
                    "target_gross": self._definition.target_gross,
                },
            )
        net = sum(item.weight for item in weights)
        return EnsembleDraft(
            weights=weights,
            budget_mode=self._definition.budget_mode,
            target_gross=self._definition.target_gross,
            decision_action=DecisionAction.TARGET,
            diagnostics=(
                f"member_gross={gross_before:.12g}",
                f"crossed_gross={gross_before - gross_after:.12g}",
            ),
            member_artifact_ids=tuple(member.artifact_id for member, _ in members),
            contributions=contributions,
            gross_before_netting=gross_before,
            gross_after_netting=gross_after,
            net_exposure=net,
            crossed_gross=gross_before - gross_after,
            residual_budget=self._definition.target_gross - gross_after,
        )

    @staticmethod
    def evidence(
        invocation: StrategyInvocation,
        strategy_id: str,
        result_artifact_id: str,
        draft: EnsembleDraft,
    ) -> EnsembleEvidence:
        return EnsembleEvidence(
            invocation_id=invocation.invocation_id,
            strategy_id=strategy_id,
            result_artifact_id=result_artifact_id,
            member_artifact_ids=draft.member_artifact_ids,
            contributions=draft.contributions,
            gross_before_netting=draft.gross_before_netting,
            gross_after_netting=draft.gross_after_netting,
            net_exposure=draft.net_exposure,
            crossed_gross=draft.crossed_gross,
            residual_budget=draft.residual_budget,
        )

    @staticmethod
    def _requirement_id(index: int) -> str:
        return f"ensemble.member.{index:03d}"

    @staticmethod
    def _consumer_role(index: int) -> str:
        return f"ensemble_member_{index:03d}"


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
        derived_bindings = tuple(
            StrategyArtifactBinding(
                consumer_role=EnsembleStrategyOperation._consumer_role(index),
                artifact_id=member.artifact_id,
            )
            for index, member in enumerate(definition.members)
        )
        if invocation.artifact_bindings and invocation.artifact_bindings != derived_bindings:
            return self._failure(
                invocation,
                "ENSEMBLE_ARTIFACT_BINDINGS_CONFLICT",
                {
                    "expected_bindings": tuple(
                        item.model_dump(mode="json") for item in derived_bindings
                    ),
                    "actual_bindings": tuple(
                        item.model_dump(mode="json") for item in invocation.artifact_bindings
                    ),
                },
            )
        selected_invocation = invocation.model_copy(update={"artifact_bindings": derived_bindings})
        operation = EnsembleStrategyOperation(definition)
        combined = self._research.invoke_strategy(operation, selected_invocation)
        if combined.status is not OutcomeStatus.COMPLETE:
            return combined
        strategy = combined.result
        if not isinstance(strategy, StrategyRunResult) or not isinstance(
            strategy.computed_draft,
            EnsembleDraft,
        ):
            return self._failure(invocation, "ENSEMBLE_RESULT_INVALID", {})
        draft = strategy.computed_draft
        evidence = operation.evidence(
            invocation,
            definition.strategy_id,
            strategy.artifact.artifact_id,
            draft,
        )
        member_dependencies = tuple(
            edge
            for edge in strategy.artifact.dependencies
            if edge.dependency_kind == "artifact"
            and edge.consumer_role.startswith("ensemble_member_")
        )
        publication = self._artifacts.publish_model(
            logical_identity=f"ensemble-evidence:{invocation.invocation_id}",
            artifact_type="ensemble_evidence",
            artifact_schema_version=2,
            producer_id=definition.strategy_id,
            payload=evidence,
            dependencies=(
                *member_dependencies,
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
        error = build_operation_error(
            operation="ensemble.run",
            stage_path="ensemble.run.compatibility",
            error_code=code,
            idempotency_identity=invocation.invocation_id,
            error_identity_seed=f"{invocation.invocation_id}:{code}",
            context=context,
            retry_preconditions=("select compatible stored member results or a flexible budget",),
        )
        return publish_failed_outcome(
            self._artifacts,
            error,
            include_publication_diagnostics=False,
        )
