"""Deterministic, point-in-time StrategyAgent public contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import pairwise
from typing import Any, Literal

import pandas as pd

from qlibx.errors import QlibxError
from qlibx.serialization import digest_dataset as _digest

OutputKind = Literal["signal", "weight", "order", "payload"]

# A violation report names the offending labels rather than only counting them: an agent
# that has to re-derive *which* row broke the boundary is one that will guess instead.
_SAMPLE_LIMIT = 5


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
            raise QlibxError(
                "QLIBX_DECISION_UNIVERSE_REDECLARED",
                f"Strategy {self.strategy_id!r} redeclares 'universe', which every Strategy "
                f"inherits",
                action=(
                    "Remove 'universe' from data_requirements and read it from "
                    "all_data_requirements."
                ),
                context={
                    "strategy_id": self.strategy_id,
                    "data_requirements": list(self.data_requirements),
                },
            )

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
                raise QlibxError(
                    "QLIBX_DECISION_AVAILABILITY_UNDETERMINED",
                    f"Dataset {self.dataset_id!r} has neither available_at nor a DatetimeIndex, "
                    f"so point-in-time visibility cannot be decided",
                    action=(
                        "Supply available_at for this dataset, or index it by a DatetimeIndex. "
                        "qlibx will not assume a dataset is visible."
                    ),
                    context={
                        "dataset": self.dataset_id,
                        "decision_time": cutoff.isoformat(),
                        "index_type": type(values.index).__name__,
                    },
                )
            late = values.index[values.index > cutoff]
            if len(late):
                raise _look_ahead(self.dataset_id, cutoff, "index", _index_violations(late))
        else:
            normalized = _availability_frame(self.dataset_id, values, availability)
            # A missing cell carries no information, so its availability cannot leak one.
            violation = normalized.gt(cutoff) & values.notna()
            if violation.any().any():
                raise _look_ahead(
                    self.dataset_id,
                    cutoff,
                    "available_at",
                    _cell_violations(values, normalized, violation),
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
            raise QlibxError(
                "QLIBX_DECISION_FEEDBACK_UNORDERED",
                "Feedback history is not ordered by confirmed_at",
                action=(
                    "Sort feedback_history by confirmed_at before building the DecisionContext; "
                    "the order is what makes 'prior feedback only' checkable."
                ),
                context={
                    "decision_time": decision_time.isoformat(),
                    "confirmed_at": [item.confirmed_at.isoformat() for item in events],
                },
            )
        unconfirmed = [item for item in events if item.confirmed_at > decision_time]
        if unconfirmed:
            raise QlibxError(
                "QLIBX_DECISION_FEEDBACK_UNCONFIRMED",
                f"Feedback history carries {len(unconfirmed)} event(s) Qlib had not confirmed "
                f"at the decision time",
                action=(
                    "Drop feedback confirmed after the decision time; a decision may only see "
                    "fills already confirmed when it is made."
                ),
                context={
                    "decision_time": decision_time.isoformat(),
                    "violation_count": len(unconfirmed),
                    "violations": [
                        {"kind": item.kind, "confirmed_at": item.confirmed_at.isoformat()}
                        for item in unconfirmed[:_SAMPLE_LIMIT]
                    ],
                },
            )
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
                raise QlibxError(
                    "QLIBX_DECISION_CHILD_DATASET_UNDECLARED",
                    f"Child requested dataset {name!r}, which the parent context does not hold",
                    action=(
                        "Request only datasets the parent declares; a child narrows its parent "
                        "and can never reach data the parent could not see."
                    ),
                    context={"dataset": name, "parent_datasets": sorted(self.datasets)},
                )
            parent = self.datasets[name]
            outside_rows = child_frame.index[~child_frame.index.isin(parent.index)]
            if len(outside_rows):
                raise _child_out_of_bounds(name, "index", outside_rows)
            outside_columns = child_frame.columns[~child_frame.columns.isin(parent.columns)]
            if len(outside_columns):
                raise _child_out_of_bounds(name, "columns", outside_columns)
            parent_subset = parent.loc[child_frame.index, child_frame.columns]
            mismatch = _frame_mismatch(parent_subset, child_frame)
            if mismatch is not None:
                raise QlibxError(
                    "QLIBX_DECISION_CHILD_OBSERVATIONS_CHANGED",
                    f"Child dataset {name!r} does not match the parent values on its own axes",
                    action=(
                        "Pass the parent slice through unchanged; a child may narrow the parent "
                        "but must never rewrite an observation."
                    ),
                    context={"dataset": name, "mismatch": mismatch},
                )
            bounded[name] = child_frame.copy(deep=True)
            if name in self.availability:
                parent_available = _availability_frame(name, parent, self.availability[name])
                expected = parent_available.loc[child_frame.index, child_frame.columns]
                supplied = requested_availability.get(name, expected)
                supplied_frame = _availability_frame(name, child_frame, supplied)
                mismatch = _frame_mismatch(expected, supplied_frame)
                if mismatch is not None:
                    raise QlibxError(
                        "QLIBX_DECISION_CHILD_AVAILABILITY_CHANGED",
                        f"Child dataset {name!r} changed the availability metadata it inherited",
                        action=(
                            "Omit availability for this dataset so the child inherits the "
                            "parent's, or supply the parent slice unchanged."
                        ),
                        context={"dataset": name, "mismatch": mismatch},
                    )
                bounded_availability[name] = supplied_frame
            elif name in requested_availability:
                raise QlibxError(
                    "QLIBX_DECISION_CHILD_AVAILABILITY_ADDED",
                    f"Child dataset {name!r} supplies available_at, but the parent holds none "
                    f"for it",
                    action=(
                        "Drop the availability entry. A child cannot make data visible that the "
                        "parent bounded by its index alone."
                    ),
                    context={"dataset": name, "parent_availability": sorted(self.availability)},
                )
        child_lookbacks = dict(lookbacks or {})
        for name in child_lookbacks:
            if name not in requested_datasets:
                raise QlibxError(
                    "QLIBX_DECISION_CHILD_LOOKBACK_UNDECLARED",
                    f"Child lookback names {name!r}, which is not a requested child dataset",
                    action="Request the dataset in the same child call, or drop the lookback.",
                    context={
                        "lookback": name,
                        "requested_datasets": sorted(requested_datasets),
                    },
                )
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
        raise QlibxError(
            "QLIBX_DECISION_DATASETS_MISSING",
            f"Strategy {definition.strategy_id!r} declares datasets the context does not "
            f"hold: {missing}",
            action=(
                "Add the declared datasets to the DecisionContext, or narrow "
                "data_requirements on the Strategy."
            ),
            context={
                "strategy_id": definition.strategy_id,
                "missing": missing,
                "declared": list(definition.all_data_requirements),
                "supplied": sorted(context.datasets),
            },
        )
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
        raise QlibxError(
            "QLIBX_DECISION_CONTEXT_MUTATED",
            f"Strategy {definition.strategy_id!r} mutated its bounded decision context",
            action=(
                "Return new objects instead of writing into context.datasets, memory, or "
                "account. A mutated context breaks the invocation digest that reproduces the run."
            ),
            context={
                "strategy_id": definition.strategy_id,
                "decision_time": context.decision_time.isoformat(),
                "invocation_id": invocation.invocation_id,
            },
        )
    if result.kind != definition.output_kind:
        raise QlibxError(
            "QLIBX_DECISION_OUTPUT_KIND_MISMATCH",
            f"Strategy {definition.strategy_id!r} declares {definition.output_kind!r} but "
            f"returned {result.kind!r}",
            action=(
                "Return the declared output_kind, or change output_kind on the "
                "StrategyDefinition to match what the program produces."
            ),
            context={
                "strategy_id": definition.strategy_id,
                "declared": definition.output_kind,
                "returned": result.kind,
            },
        )
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
    except (TypeError, ValueError, QlibxError) as error:
        # A rejected what-if is an answer, not a crash: the caller keeps its own account
        # and reads why the child was refused. Carrying `error_code` keeps that reason
        # machine-readable instead of a string an agent has to pattern-match.
        return NestedResearchResult(
            "invalid",
            None,
            None,
            {
                "evaluator_id": request.evaluator_id,
                "error": str(error),
                "error_code": getattr(error, "code", None),
            },
            parent_account_digest,
        )
    observed_account_digest = _digest(parent.account)
    if observed_account_digest != parent_account_digest:
        raise QlibxError(
            "QLIBX_DECISION_PARENT_ACCOUNT_MUTATED",
            "Nested research changed the parent account state",
            action=(
                "Remove the account write from the child program. Nested research explores "
                "what-ifs and holds no authority to mutate the account it branched from."
            ),
            context={
                "evaluator_id": request.evaluator_id,
                "expected_account_digest": parent_account_digest,
                "observed_account_digest": observed_account_digest,
            },
        )
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
    for position, (current, following) in enumerate(pairwise(ordered)):
        if current.decision_time >= following.decision_time:
            raise QlibxError(
                "QLIBX_DECISION_SEQUENCE_UNORDERED",
                f"Decision contexts must strictly increase in decision_time, but position "
                f"{position + 1} does not follow position {position}",
                action=(
                    "Sort the contexts by decision_time and remove duplicates. Memory flows "
                    "forward through the sequence, so the order defines the result."
                ),
                context={
                    "position": position,
                    "decision_time": current.decision_time.isoformat(),
                    "next_decision_time": following.decision_time.isoformat(),
                    "context_count": len(ordered),
                },
            )
    start = checkpoint.next_position if checkpoint else 0
    stop = len(ordered) if end_position is None else end_position
    if start < 0 or stop < start or stop > len(ordered):
        raise QlibxError(
            "QLIBX_DECISION_SEQUENCE_BOUNDARY_INVALID",
            f"Sequence boundary [{start}, {stop}) does not lie inside the {len(ordered)} "
            f"supplied contexts",
            action=(
                "Resume from the checkpoint's next_position and keep end_position within the "
                "contexts you passed."
            ),
            context={
                "start": start,
                "end": stop,
                "context_count": len(ordered),
                "resumed_from_checkpoint": checkpoint is not None,
            },
        )
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
    dataset_id: str,
    values: pd.DataFrame,
    availability: pd.DataFrame | pd.Series,
) -> pd.DataFrame:
    if isinstance(availability, pd.Series):
        _require_matching_axis(dataset_id, "index", values.index, availability.index)
        frame = pd.DataFrame(
            {column: availability for column in values.columns},
            index=values.index,
        )
    else:
        frame = availability
    _require_matching_axis(dataset_id, "index", values.index, frame.index)
    _require_matching_axis(dataset_id, "columns", values.columns, frame.columns)
    return frame.apply(lambda column: pd.to_datetime(column, errors="raise"))


def _require_matching_axis(
    dataset_id: str,
    axis: str,
    expected: pd.Index,
    actual: pd.Index,
) -> None:
    """Refuse availability metadata that does not line up cell-for-cell with its dataset.

    A misaligned axis would silently pair one cell's value with another cell's visibility,
    which is a look-ahead leak that no later check could see.
    """
    if actual.equals(expected):
        return
    raise QlibxError(
        "QLIBX_DECISION_AVAILABILITY_AXES_MISMATCH",
        f"available_at for dataset {dataset_id!r} does not match the dataset {axis}",
        action=(
            f"Build available_at on the dataset's own {axis}, in the same order, so each "
            f"visibility timestamp describes the cell beside it."
        ),
        context={
            "dataset": dataset_id,
            "axis": axis,
            "dataset_length": len(expected),
            "availability_length": len(actual),
            "missing_from_available_at": _labels(expected.difference(actual)),
            "unexpected_in_available_at": _labels(actual.difference(expected)),
        },
    )


def _look_ahead(
    dataset_id: str,
    cutoff: pd.Timestamp,
    boundary: str,
    violations: tuple[int, list[Any]],
) -> QlibxError:
    """Build the no-look-ahead refusal, naming what was visible too early.

    This is the most expensive failure the product prevents, so the report has to be
    actionable on its own: which dataset, which boundary decided it, and which specific
    observations crossed the line.
    """
    count, sample = violations
    return QlibxError(
        "QLIBX_DECISION_LOOK_AHEAD",
        f"Dataset {dataset_id!r} carries {count} observation(s) that were not available at "
        f"the decision time",
        action=(
            "Trim the dataset to the decision time, or supply available_at when the "
            "observation timestamp is not the timestamp the observation became knowable. "
            "Never widen the decision time to admit the data."
        ),
        context={
            "dataset": dataset_id,
            "decision_time": cutoff.isoformat(),
            "boundary": boundary,
            "violation_count": count,
            "violations": sample,
        },
    )


def _index_violations(late: pd.Index) -> tuple[int, list[Any]]:
    return len(late), _labels(late)


def _cell_violations(
    values: pd.DataFrame,
    normalized: pd.DataFrame,
    violation: pd.DataFrame,
) -> tuple[int, list[Any]]:
    rows, columns = violation.to_numpy().nonzero()
    sample = [
        {
            "row": _label(values.index[row]),
            "column": _label(values.columns[column]),
            "available_at": _label(normalized.iat[row, column]),
        }
        for row, column in zip(rows[:_SAMPLE_LIMIT], columns[:_SAMPLE_LIMIT], strict=True)
    ]
    return len(rows), sample


def _child_out_of_bounds(dataset: str, axis: str, outside: pd.Index) -> QlibxError:
    """Refuse a child that names labels its parent never held, on either axis.

    Row and column escapes share one code and separate on ``context['axis']``: they are the
    same violation seen from two directions, and a single code keeps the raise site literal
    enough for the documentation guard to see it.
    """
    return QlibxError(
        "QLIBX_DECISION_CHILD_AXIS_OUT_OF_BOUNDS",
        f"Child dataset {dataset!r} carries {len(outside)} {axis} label(s) the parent does "
        f"not hold",
        action=(
            f"Slice the child out of the parent frame. A child narrows its parent, so every "
            f"{axis} label it names must already exist there."
        ),
        context={
            "dataset": dataset,
            "axis": axis,
            "violation_count": len(outside),
            "violations": _labels(outside),
        },
    )


def _label(value: Any) -> str:
    return value.isoformat() if isinstance(value, pd.Timestamp) else str(value)


def _labels(index: pd.Index) -> list[str]:
    return [_label(value) for value in index[:_SAMPLE_LIMIT]]


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


def _frame_mismatch(left: pd.DataFrame, right: pd.DataFrame) -> str | None:
    """Report *why* two frames differ, or None when they match exactly.

    The comparison already knows which cell or dtype broke; discarding that and reporting
    only "changed" makes the caller re-derive it by hand.
    """
    try:
        pd.testing.assert_frame_equal(left, right, check_dtype=True)
    except AssertionError as error:
        return str(error).strip()
    return None
