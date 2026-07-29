"""Deterministic, point-in-time StrategyAgent public contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import pairwise
from typing import Any, Literal

import pandas as pd

from qlibx.serialization import digest_dataset as _digest

OutputKind = Literal["signal", "weight", "order", "payload"]


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    """Stable instance identity, separate from the implementation class/function."""

    strategy_id: str
    name: str
    parameters: Mapping[str, Any]
    data_requirements: tuple[str, ...]
    output_kind: OutputKind
    version: str = "1"

    def __post_init__(self) -> None:
        if "universe" in self.data_requirements:
            raise ValueError("universe is inherited and must not be redeclared")

    @property
    def all_data_requirements(self) -> tuple[str, ...]:
        return ("universe", *self.data_requirements)


@dataclass(frozen=True, slots=True)
class FeedbackEvent:
    """Qlib-confirmed feedback visible only at or after ``confirmed_at``."""

    confirmed_at: pd.Timestamp
    kind: str
    payload: Any

    def __post_init__(self) -> None:
        object.__setattr__(self, "confirmed_at", pd.Timestamp(self.confirmed_at))


@dataclass(frozen=True, slots=True)
class DatasetWindow:
    """One dataset with an independent point-in-time availability boundary."""

    dataset_id: str
    values: pd.DataFrame
    available_at: pd.DataFrame | pd.Series | None = None
    lookback: str | None = None

    def bounded(self, decision_time: pd.Timestamp) -> DatasetWindow:
        values = self.values.copy(deep=True)
        availability = _copy_pandas(self.available_at)
        cutoff = pd.Timestamp(decision_time)
        if availability is None:
            if not isinstance(values.index, pd.DatetimeIndex):
                raise ValueError(f"dataset {self.dataset_id} needs available_at or a DatetimeIndex")
            if len(values.index) and values.index.max() > cutoff:
                raise ValueError(
                    f"dataset {self.dataset_id} contains observations available after decision time"
                )
        else:
            normalized = _availability_frame(values, availability)
            visible = values.notna()
            violation = normalized.gt(cutoff) & visible
            if violation.any().any():
                raise ValueError(
                    f"dataset {self.dataset_id} contains observations available after decision time"
                )
        return DatasetWindow(self.dataset_id, values, availability, self.lookback)


@dataclass(frozen=True, slots=True)
class DecisionContext:
    decision_time: pd.Timestamp
    datasets: Mapping[str, pd.DataFrame]
    feedback: Mapping[str, Any] = field(default_factory=dict)
    memory: Mapping[str, Any] = field(default_factory=dict)
    seed: int = 0
    availability: Mapping[str, pd.DataFrame | pd.Series] = field(default_factory=dict)
    dataset_ids: Mapping[str, str] = field(default_factory=dict)
    lookbacks: Mapping[str, str] = field(default_factory=dict)
    feedback_history: tuple[FeedbackEvent, ...] = ()
    account: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        decision_time = pd.Timestamp(self.decision_time)
        object.__setattr__(self, "decision_time", decision_time)
        bounded: dict[str, pd.DataFrame] = {}
        bounded_availability: dict[str, pd.DataFrame | pd.Series] = {}
        for name, frame in self.datasets.items():
            window = DatasetWindow(
                self.dataset_ids.get(name, name),
                frame,
                self.availability.get(name),
                self.lookbacks.get(name),
            ).bounded(decision_time)
            bounded[name] = window.values
            if window.available_at is not None:
                bounded_availability[name] = window.available_at
        events = tuple(self.feedback_history)
        if tuple(sorted(events, key=lambda item: item.confirmed_at)) != events:
            raise ValueError("feedback history must be ordered by confirmed_at")
        if any(item.confirmed_at > decision_time for item in events):
            raise ValueError("feedback history contains unconfirmed future feedback")
        object.__setattr__(self, "datasets", bounded)
        object.__setattr__(self, "availability", bounded_availability)
        object.__setattr__(self, "feedback", _deep_copy(dict(self.feedback)))
        object.__setattr__(self, "memory", _deep_copy(dict(self.memory)))
        object.__setattr__(self, "account", _deep_copy(dict(self.account)))

    def child(
        self,
        *,
        datasets: Mapping[str, pd.DataFrame],
        availability: Mapping[str, pd.DataFrame | pd.Series] | None = None,
        lookbacks: Mapping[str, str] | None = None,
        seed: int | None = None,
    ) -> DecisionContext:
        """Create a child capability that can only narrow its parent's data."""
        requested_datasets = dict(datasets)
        if "universe" in self.datasets and "universe" not in requested_datasets:
            requested_datasets["universe"] = self.datasets["universe"]
        bounded: dict[str, pd.DataFrame] = {}
        bounded_availability: dict[str, pd.DataFrame | pd.Series] = {}
        requested_availability = availability or {}
        for name, child_frame in requested_datasets.items():
            if name not in self.datasets:
                raise ValueError(f"child requested undeclared dataset: {name}")
            parent = self.datasets[name]
            if not child_frame.index.isin(parent.index).all():
                raise ValueError(f"child dataset {name} exceeds parent time bounds")
            if not child_frame.columns.isin(parent.columns).all():
                raise ValueError(f"child dataset {name} exceeds parent column bounds")
            parent_subset = parent.loc[child_frame.index, child_frame.columns]
            if not _frames_equal_with_nan(parent_subset, child_frame):
                raise ValueError(f"child dataset {name} changed parent observations")
            bounded[name] = child_frame.copy(deep=True)
            if name in self.availability:
                parent_available = _availability_frame(parent, self.availability[name])
                expected = parent_available.loc[child_frame.index, child_frame.columns]
                supplied = requested_availability.get(name, expected)
                supplied_frame = _availability_frame(child_frame, supplied)
                if not _frames_equal_with_nan(expected, supplied_frame):
                    raise ValueError(f"child dataset {name} changed availability metadata")
                bounded_availability[name] = supplied_frame
            elif name in requested_availability:
                raise ValueError(f"child dataset {name} added availability metadata")
        child_lookbacks = dict(lookbacks or {})
        for name in child_lookbacks:
            if name not in requested_datasets:
                raise ValueError(f"child lookback has no requested dataset: {name}")
        return DecisionContext(
            self.decision_time,
            bounded,
            feedback=dict(self.feedback),
            memory=dict(self.memory),
            seed=self.seed if seed is None else seed,
            availability=bounded_availability,
            dataset_ids={name: self.dataset_ids.get(name, name) for name in bounded},
            lookbacks=child_lookbacks,
            feedback_history=self.feedback_history,
            account=dict(self.account),
        )

    def detached_copy(self) -> DecisionContext:
        return DecisionContext(
            self.decision_time,
            {name: frame.copy(deep=True) for name, frame in self.datasets.items()},
            feedback=dict(self.feedback),
            memory=dict(self.memory),
            seed=self.seed,
            availability={name: _copy_pandas(value) for name, value in self.availability.items()},
            dataset_ids=dict(self.dataset_ids),
            lookbacks=dict(self.lookbacks),
            feedback_history=self.feedback_history,
            account=dict(self.account),
        )


@dataclass(frozen=True, slots=True)
class IntermediateRecord:
    name: str
    sequence: int
    payload: Any
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecisionResult:
    kind: OutputKind
    payload: Any
    memory: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    intermediates: tuple[IntermediateRecord, ...] = ()
    invocation_id: str | None = None
    primary_result_id: str | None = None
    result_id: str | None = None


@dataclass(frozen=True, slots=True)
class FrozenInvocation:
    invocation_id: str
    strategy_id: str
    strategy_version: str
    decision_time: str
    effective_config_id: str
    dependency_versions: Mapping[str, str]
    dataset_digests: Mapping[str, str]
    feedback_digest: str
    memory_digest: str
    account_digest: str
    seed: int


@dataclass(frozen=True, slots=True)
class NestedResearchRequest:
    definition: StrategyDefinition
    datasets: Mapping[str, pd.DataFrame]
    evaluator_id: str
    seed: int
    resource_limit: Mapping[str, int]
    availability: Mapping[str, pd.DataFrame | pd.Series] = field(default_factory=dict)
    lookbacks: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NestedResearchResult:
    status: Literal["successful", "failed", "invalid"]
    decision: DecisionResult | None
    metric: float | None
    diagnostics: Mapping[str, Any]
    parent_account_digest: str


@dataclass(frozen=True, slots=True)
class StrategyCheckpoint:
    next_position: int
    memory: Mapping[str, Any]
    previous_result_id: str | None


@dataclass(frozen=True, slots=True)
class StrategySequence:
    results: tuple[DecisionResult, ...]
    checkpoint: StrategyCheckpoint


DecisionProgram = Callable[[DecisionContext, Mapping[str, Any]], DecisionResult]
NestedEvaluator = Callable[[DecisionResult], float]


def freeze_invocation(
    definition: StrategyDefinition,
    context: DecisionContext,
    *,
    effective_config_id: str = "",
    dependency_versions: Mapping[str, str] | None = None,
) -> FrozenInvocation:
    dependencies = dict(dependency_versions or {})
    dataset_digests = {
        name: _digest(
            {
                "dataset_id": context.dataset_ids.get(name, name),
                "values": frame,
                "available_at": context.availability.get(name),
                "lookback": context.lookbacks.get(name),
            }
        )
        for name, frame in sorted(context.datasets.items())
    }
    body = {
        "definition": definition,
        "decision_time": context.decision_time,
        "effective_config_id": effective_config_id,
        "dependencies": dependencies,
        "datasets": dataset_digests,
        "feedback": context.feedback,
        "feedback_history": context.feedback_history,
        "memory": context.memory,
        "account": context.account,
        "seed": context.seed,
    }
    return FrozenInvocation(
        invocation_id=_digest(body),
        strategy_id=definition.strategy_id,
        strategy_version=definition.version,
        decision_time=context.decision_time.isoformat(),
        effective_config_id=effective_config_id,
        dependency_versions=dependencies,
        dataset_digests=dataset_digests,
        feedback_digest=_digest((context.feedback, context.feedback_history)),
        memory_digest=_digest(context.memory),
        account_digest=_digest(context.account),
        seed=context.seed,
    )


def run_decision(
    definition: StrategyDefinition,
    program: DecisionProgram,
    context: DecisionContext,
    *,
    effective_config_id: str = "",
    dependency_versions: Mapping[str, str] | None = None,
) -> DecisionResult:
    missing = sorted(set(definition.all_data_requirements) - set(context.datasets))
    if missing:
        raise ValueError(f"strategy datasets are missing: {missing}")
    invocation = freeze_invocation(
        definition,
        context,
        effective_config_id=effective_config_id,
        dependency_versions=dependency_versions,
    )
    detached = context.detached_copy()
    before = _digest(detached)
    result = program(detached, _deep_copy(dict(definition.parameters)))
    if _digest(detached) != before:
        raise ValueError("strategy mutated its bounded decision context")
    if result.kind != definition.output_kind:
        raise ValueError(f"strategy declared {definition.output_kind} but returned {result.kind}")
    primary_id = _digest(
        {
            "invocation_id": invocation.invocation_id,
            "kind": result.kind,
            "payload": result.payload,
            "memory": result.memory,
        }
    )
    result_id = _digest(
        {
            "primary_result_id": primary_id,
            "diagnostics": result.diagnostics,
            "intermediates": result.intermediates,
        }
    )
    return replace(
        result,
        invocation_id=invocation.invocation_id,
        primary_result_id=primary_id,
        result_id=result_id,
    )


def compose_child_result(
    child: DecisionResult,
    transform: Callable[[Any], Any],
    *,
    kind: OutputKind | None = None,
    record_name: str = "child_output",
) -> DecisionResult:
    """Reuse a child's declared payload without accessing its private strategy object."""
    output_kind = child.kind if kind is None else kind
    record = IntermediateRecord(
        record_name,
        0,
        child.payload,
        {"child_result_id": child.result_id},
    )
    return DecisionResult(
        output_kind,
        transform(_deep_copy(child.payload)),
        diagnostics={"composed_from": child.result_id},
        intermediates=(record,),
    )


def evaluate_child(
    parent: DecisionContext,
    request: NestedResearchRequest,
    program: DecisionProgram,
    evaluator: NestedEvaluator,
) -> NestedResearchResult:
    """Evaluate an isolated what-if child with no account mutation authority."""
    parent_account_digest = _digest(parent.account)
    try:
        child = parent.child(
            datasets=request.datasets,
            availability=request.availability,
            lookbacks=request.lookbacks,
            seed=request.seed,
        )
        decision = run_decision(request.definition, program, child)
        metric = float(evaluator(decision))
    except (TypeError, ValueError) as error:
        return NestedResearchResult(
            "invalid",
            None,
            None,
            {"evaluator_id": request.evaluator_id, "error": str(error)},
            parent_account_digest,
        )
    if _digest(parent.account) != parent_account_digest:
        raise RuntimeError("nested research changed parent account state")
    return NestedResearchResult(
        "successful",
        decision,
        metric,
        {
            "evaluator_id": request.evaluator_id,
            "resource_limit": dict(request.resource_limit),
        },
        parent_account_digest,
    )


def run_decision_sequence(
    definition: StrategyDefinition,
    program: DecisionProgram,
    contexts: Sequence[DecisionContext],
    *,
    checkpoint: StrategyCheckpoint | None = None,
    end_position: int | None = None,
) -> StrategySequence:
    """Run ordered decisions; only prior Qlib-confirmed feedback reaches each step."""
    ordered = list(contexts)
    if any(
        current.decision_time >= following.decision_time for current, following in pairwise(ordered)
    ):
        raise ValueError("decision contexts must be strictly ordered")
    start = checkpoint.next_position if checkpoint else 0
    stop = len(ordered) if end_position is None else end_position
    if start < 0 or stop < start or stop > len(ordered):
        raise ValueError("invalid sequence boundary")
    memory: Mapping[str, Any] = checkpoint.memory if checkpoint else {}
    previous_result_id = checkpoint.previous_result_id if checkpoint else None
    results: list[DecisionResult] = []
    for context in ordered[start:stop]:
        effective = replace(context, memory=_deep_copy(dict(memory)))
        result = run_decision(definition, program, effective)
        results.append(result)
        memory = _deep_copy(dict(result.memory))
        previous_result_id = result.result_id
    return StrategySequence(
        tuple(results),
        StrategyCheckpoint(stop, memory, previous_result_id),
    )


def _availability_frame(
    values: pd.DataFrame,
    availability: pd.DataFrame | pd.Series,
) -> pd.DataFrame:
    if isinstance(availability, pd.Series):
        if not availability.index.equals(values.index):
            raise ValueError("available_at index must match dataset index")
        frame = pd.DataFrame(
            {column: availability for column in values.columns},
            index=values.index,
        )
    else:
        frame = availability
    if not frame.index.equals(values.index) or not frame.columns.equals(values.columns):
        raise ValueError("available_at axes must match dataset axes")
    return frame.apply(lambda column: pd.to_datetime(column, errors="raise"))


def _copy_pandas(value: Any) -> Any:
    return value.copy(deep=True) if isinstance(value, (pd.DataFrame, pd.Series)) else value


def _deep_copy(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return value.copy(deep=True)
    if isinstance(value, pd.Series):
        return value.copy(deep=True)
    if isinstance(value, Mapping):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_deep_copy(item) for item in value)
    if isinstance(value, list):
        return [_deep_copy(item) for item in value]
    return value


def _frames_equal_with_nan(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(left, right, check_dtype=True)
    except AssertionError:
        return False
    return True
