"""Deterministic signed-alpha transforms, budget policies, and diagnostics.

Signal operations and weight-scaling (budget) policies are both declared in registries
rather than in branching dispatch code. Adding an operation or a scaling rule means
registering one ``OperationSpec`` or ``BudgetPolicySpec``; nothing in this module's
dispatch, lineage, or documentation surface has to change. Project-local code and
validated ``signal_transform`` extensions register through the same door, so a custom
operation composes with built-ins and carries the same lineage.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from qlibx.errors import unknown_name


@dataclass(frozen=True, slots=True)
class ExposureSummary:
    long: pd.Series
    short: pd.Series
    gross: pd.Series
    net: pd.Series
    coverage: pd.Series
    missingness: pd.Series


@dataclass(frozen=True, slots=True)
class OperationContract:
    """Versioned semantics of one applied operation; becomes result lineage."""

    operation_id: str
    version: str
    axis: str
    tie_behavior: str
    nan_behavior: str
    minimum_observations: int | None
    group_missing_behavior: str
    dtype: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    summary: str = ""
    selection_behavior: str = "not_applicable"
    implementation: str = "builtin"
    implementation_digest: str | None = None


@dataclass(frozen=True, slots=True)
class TransformResult:
    values: pd.DataFrame
    lineage: tuple[OperationContract, ...]
    neutrality_warning: str | None = None


@dataclass(frozen=True, slots=True)
class ExposureArtifact:
    analyzer_id: str
    analyzer_version: str
    input_id: str
    dataset_ids: Mapping[str, str]
    estimation_window: tuple[str, str]
    method: str
    summary: ExposureSummary
    market_exposure: pd.Series | None
    benchmark_exposure: pd.Series | None
    group_exposure: pd.DataFrame | None
    factor_exposure: pd.DataFrame | None
    intended_realized_gap: ExposureSummary | None
    coverage: pd.Series
    missingness: pd.Series
    neutrality_warning: str


NEUTRALITY_WARNING = (
    "A transform is not proof of exact market, benchmark, industry, sector, or factor neutrality."
)


# --------------------------------------------------------------------------------------
# Operation registry
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OperationSpec:
    """Declared semantics plus the implementation of one deterministic operation.

    ``apply`` is called as ``apply(values, **parameters)``, or as
    ``apply(values, groups=groups, **parameters)`` when ``requires_groups`` is set.
    ``resolve_minimum_observations`` lets a parameterized window override the declared
    default so lineage records the count actually required.
    """

    name: str
    operation_id: str
    version: str
    axis: str
    tie_behavior: str
    nan_behavior: str
    minimum_observations: int | None
    group_missing_behavior: str
    dtype: str
    summary: str
    apply: Callable[..., pd.DataFrame]
    parameters: Mapping[str, str] = field(default_factory=dict)
    required_parameters: tuple[str, ...] = ()
    requires_groups: bool = False
    selection_behavior: str = "not_applicable"
    neutrality_warning: str | None = None
    implementation: str = "builtin"
    implementation_digest: str | None = None
    resolve_minimum_observations: Callable[[Mapping[str, Any]], int | None] | None = None

    def contract(self, parameters: Mapping[str, Any]) -> OperationContract:
        minimum = self.minimum_observations
        if self.resolve_minimum_observations is not None:
            minimum = self.resolve_minimum_observations(parameters)
        return OperationContract(
            operation_id=self.operation_id,
            version=self.version,
            axis=self.axis,
            tie_behavior=self.tie_behavior,
            nan_behavior=self.nan_behavior,
            minimum_observations=None if minimum is None else int(minimum),
            group_missing_behavior=self.group_missing_behavior,
            dtype=self.dtype,
            parameters=dict(parameters),
            summary=self.summary,
            selection_behavior=self.selection_behavior,
            implementation=self.implementation,
            implementation_digest=self.implementation_digest,
        )

    def describe(self) -> dict[str, Any]:
        """Return the agent-facing contract without executing the operation."""
        return {
            "name": self.name,
            "operation_id": self.operation_id,
            "version": self.version,
            "summary": self.summary,
            "axis": self.axis,
            "tie_behavior": self.tie_behavior,
            "nan_behavior": self.nan_behavior,
            "minimum_observations": self.minimum_observations,
            "group_missing_behavior": self.group_missing_behavior,
            "selection_behavior": self.selection_behavior,
            "dtype": self.dtype,
            "parameters": dict(self.parameters),
            "required_parameters": list(self.required_parameters),
            "requires_groups": self.requires_groups,
            "neutrality_warning": self.neutrality_warning,
            "implementation": self.implementation,
        }


class OperationRegistry:
    """Name-to-``OperationSpec`` registry backing dispatch, lineage, and documentation."""

    def __init__(self) -> None:
        self._specs: dict[str, OperationSpec] = {}

    def register(self, spec: OperationSpec, *, replace_existing: bool = False) -> OperationSpec:
        if spec.name in self._specs and not replace_existing:
            raise ValueError(f"alpha operation is already registered: {spec.name}")
        missing = sorted(set(spec.required_parameters) - set(spec.parameters))
        if missing:
            raise ValueError(f"operation {spec.name} requires undeclared parameters: {missing}")
        self._specs[spec.name] = spec
        return spec

    def unregister(self, name: str) -> None:
        self._specs.pop(name, None)

    def get(self, name: str) -> OperationSpec:
        try:
            return self._specs[name]
        except KeyError as error:
            raise unknown_name(
                "QLIBX_ALPHA_OPERATION_UNKNOWN", "alpha operation", name, self._specs
            ) from error

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def describe(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._specs[name].describe() for name in self.names())


OPERATIONS = OperationRegistry()


def register_operation(spec: OperationSpec, *, replace_existing: bool = False) -> OperationSpec:
    """Register a built-in, project-local, or extension-backed signal operation."""
    return OPERATIONS.register(spec, replace_existing=replace_existing)


def operation_spec(name: str) -> OperationSpec:
    return OPERATIONS.get(name)


def list_operations() -> tuple[dict[str, Any], ...]:
    """Return every installed operation contract for help, schema, and skill output."""
    return OPERATIONS.describe()


# --------------------------------------------------------------------------------------
# Built-in operations
# --------------------------------------------------------------------------------------


def cross_sectional_rank(values: pd.DataFrame) -> pd.DataFrame:
    """Return centered percentile ranks in [-0.5, 0.5], preserving missing values."""
    return values.rank(axis=1, method="average", pct=True) - 0.5


def cross_sectional_demean(values: pd.DataFrame) -> pd.DataFrame:
    return values.sub(values.mean(axis=1), axis=0)


def cross_sectional_zscore(values: pd.DataFrame, *, minimum_count: int = 2) -> pd.DataFrame:
    count = values.count(axis=1)
    mean = values.mean(axis=1)
    scale = values.std(axis=1, ddof=0).replace(0.0, pd.NA)
    result = values.sub(mean, axis=0).div(scale, axis=0)
    return result.where(count.ge(minimum_count), pd.NA)


def winsorize(values: pd.DataFrame, *, lower: float = 0.01, upper: float = 0.99) -> pd.DataFrame:
    if not 0 <= lower <= upper <= 1:
        raise ValueError("winsorize quantiles must satisfy 0 <= lower <= upper <= 1")
    floors = values.quantile(lower, axis=1)
    ceilings = values.quantile(upper, axis=1)
    return values.clip(lower=floors, upper=ceilings, axis=0)


def clip(values: pd.DataFrame, *, lower: float | None = None, upper: float | None = None):
    """Clip to explicit absolute bounds; missing observations stay missing."""
    if lower is None and upper is None:
        raise ValueError("clip requires an explicit lower or upper bound")
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("clip requires lower <= upper")
    return values.clip(lower=lower, upper=upper)


def group_demean(values: pd.DataFrame, groups: pd.DataFrame) -> pd.DataFrame:
    """Demean each date within explicit ticker groups; missing groups stay missing."""
    values, groups = values.align(groups, join="left")
    result = pd.DataFrame(index=values.index, columns=values.columns, dtype="float64")
    for date in values.index:
        row = values.loc[date]
        labels = groups.loc[date]
        valid = row.notna() & labels.notna()
        result.loc[date, valid] = row[valid] - row[valid].groupby(labels[valid]).transform("mean")
    return result


def lag(values: pd.DataFrame, *, periods: int = 1) -> pd.DataFrame:
    """Shift each ticker forward in time; the first ``periods`` rows become missing."""
    if periods < 1:
        raise ValueError("periods must be positive")
    return values.shift(periods)


def rolling_mean(values: pd.DataFrame, *, window: int) -> pd.DataFrame:
    if window < 1:
        raise ValueError("window must be positive")
    return values.rolling(window, min_periods=window).mean()


def rolling_std(values: pd.DataFrame, *, window: int, ddof: int = 1) -> pd.DataFrame:
    if window < 1:
        raise ValueError("window must be positive")
    if ddof < 0 or ddof >= window:
        raise ValueError("ddof must satisfy 0 <= ddof < window")
    return values.rolling(window, min_periods=window).std(ddof=ddof)


def linear_decay(values: pd.DataFrame, *, window: int) -> pd.DataFrame:
    if window < 1:
        raise ValueError("window must be positive")
    weights = pd.Series(range(1, window + 1), dtype="float64")
    denominator = float(weights.sum())
    return values.rolling(window, min_periods=window).apply(
        lambda series: float(series.reset_index(drop=True).mul(weights).sum()) / denominator,
        raw=False,
    )


def hump(values: pd.DataFrame, *, maximum_change: float) -> pd.DataFrame:
    """Limit each ticker's step change without filling missing observations.

    A missing observation is preserved and breaks the chain: the next observed value
    restarts the limiter instead of propagating missingness for the rest of the series.
    """
    if maximum_change < 0:
        raise ValueError("maximum_change must be non-negative")
    result = values.copy().astype("float64")
    for offset in range(1, len(result.index)):
        previous = result.iloc[offset - 1]
        current = result.iloc[offset]
        delta = current.sub(previous).clip(-maximum_change, maximum_change)
        limited = previous.add(delta)
        # Where the previous value is missing there is nothing to limit against, so the
        # current observation passes through unchanged rather than becoming missing.
        result.iloc[offset] = limited.where(previous.notna(), current).where(current.notna(), pd.NA)
    return result


def top_bottom(values: pd.DataFrame, *, count: int) -> pd.DataFrame:
    """Select the ``count`` highest as +1 and the ``count`` lowest as -1.

    A date with fewer than ``2 * count`` valid observations cannot produce a disjoint
    selection, so it fails explicitly instead of silently assigning one name to both
    sides (where the short assignment would have won).
    """
    if count < 1:
        raise ValueError("count must be positive")
    valid = values.notna().sum(axis=1)
    insufficient = valid.lt(2 * count)
    if insufficient.any():
        offending = [str(label) for label in values.index[insufficient][:5]]
        raise ValueError(
            f"top_bottom requires at least {2 * count} valid observations per date; "
            f"insufficient on {int(insufficient.sum())} date(s), for example {offending}"
        )
    ranks_ascending = values.rank(axis=1, method="first", ascending=True)
    ranks_descending = values.rank(axis=1, method="first", ascending=False)
    selected = pd.DataFrame(0.0, index=values.index, columns=values.columns)
    selected = selected.mask(ranks_descending.le(count), 1.0)
    selected = selected.mask(ranks_ascending.le(count), -1.0)
    return selected.where(values.notna(), pd.NA)


def per_name_cap(values: pd.DataFrame, *, maximum_weight: float) -> pd.DataFrame:
    """Bound each name's absolute weight without changing its sign or missingness."""
    if maximum_weight <= 0:
        raise ValueError("maximum_weight must be positive")
    return values.clip(lower=-maximum_weight, upper=maximum_weight)


def _register_builtins() -> None:
    register_operation(
        OperationSpec(
            name="cross_sectional_rank",
            operation_id="qlibx.alpha.cross_sectional_rank",
            version="1",
            axis="date_by_ticker",
            tie_behavior="average_percentile_rank",
            nan_behavior="preserve",
            minimum_observations=1,
            group_missing_behavior="not_applicable",
            dtype="float64",
            summary="Centered cross-sectional percentile rank in [-0.5, 0.5].",
            apply=cross_sectional_rank,
        )
    )
    register_operation(
        OperationSpec(
            name="cross_sectional_demean",
            operation_id="qlibx.alpha.cross_sectional_demean",
            version="1",
            axis="date_by_ticker",
            tie_behavior="not_applicable",
            nan_behavior="exclude_from_mean_and_preserve",
            minimum_observations=1,
            group_missing_behavior="not_applicable",
            dtype="float64",
            summary="Subtract each date's cross-sectional mean.",
            apply=cross_sectional_demean,
            neutrality_warning=NEUTRALITY_WARNING,
        )
    )
    register_operation(
        OperationSpec(
            name="cross_sectional_zscore",
            operation_id="qlibx.alpha.cross_sectional_zscore",
            version="1",
            axis="date_by_ticker",
            tie_behavior="not_applicable",
            nan_behavior="exclude_from_moments_and_preserve",
            minimum_observations=2,
            group_missing_behavior="not_applicable",
            dtype="float64",
            summary="Standardize each date by its population mean and standard deviation.",
            apply=cross_sectional_zscore,
            parameters={
                "minimum_count": "minimum valid observations per date; fewer produces missing"
            },
            resolve_minimum_observations=lambda parameters: int(parameters.get("minimum_count", 2)),
            neutrality_warning=NEUTRALITY_WARNING,
        )
    )
    register_operation(
        OperationSpec(
            name="winsorize",
            operation_id="qlibx.alpha.winsorize",
            version="1",
            axis="date_by_ticker",
            tie_behavior="not_applicable",
            nan_behavior="exclude_from_quantiles_and_preserve",
            minimum_observations=1,
            group_missing_behavior="not_applicable",
            dtype="float64",
            summary="Clip each date to its own lower/upper cross-sectional quantiles.",
            apply=winsorize,
            parameters={
                "lower": "lower quantile in [0, 1]",
                "upper": "upper quantile in [0, 1] and >= lower",
            },
        )
    )
    register_operation(
        OperationSpec(
            name="clip",
            operation_id="qlibx.alpha.clip",
            version="1",
            axis="date_by_ticker",
            tie_behavior="not_applicable",
            nan_behavior="preserve",
            minimum_observations=1,
            group_missing_behavior="not_applicable",
            dtype="float64",
            summary="Clip to explicit absolute bounds shared by every date and ticker.",
            apply=clip,
            parameters={
                "lower": "absolute lower bound or None",
                "upper": "absolute upper bound or None",
            },
        )
    )
    register_operation(
        OperationSpec(
            name="group_demean",
            operation_id="qlibx.alpha.group_demean",
            version="1",
            axis="date_by_ticker_with_group",
            tie_behavior="not_applicable",
            nan_behavior="exclude_from_group_mean_and_preserve",
            minimum_observations=1,
            group_missing_behavior="missing_group_produces_missing_output",
            dtype="float64",
            summary="Subtract each date's group mean using explicit point-in-time labels.",
            apply=group_demean,
            requires_groups=True,
            neutrality_warning=NEUTRALITY_WARNING,
        )
    )
    register_operation(
        OperationSpec(
            name="lag",
            operation_id="qlibx.alpha.lag",
            version="1",
            axis="time_by_ticker",
            tie_behavior="not_applicable",
            nan_behavior="leading_rows_become_missing",
            minimum_observations=2,
            group_missing_behavior="not_applicable",
            dtype="float64",
            summary="Shift each ticker forward by whole index positions.",
            apply=lag,
            parameters={"periods": "positive number of index positions to shift"},
            resolve_minimum_observations=lambda parameters: int(parameters.get("periods", 1)) + 1,
        )
    )
    register_operation(
        OperationSpec(
            name="rolling_mean",
            operation_id="qlibx.alpha.rolling_mean",
            version="1",
            axis="time_by_ticker",
            tie_behavior="not_applicable",
            nan_behavior="full_window_required",
            minimum_observations=None,
            group_missing_behavior="not_applicable",
            dtype="float64",
            summary="Trailing mean over a full window of consecutive index positions.",
            apply=rolling_mean,
            parameters={"window": "positive number of trailing index positions"},
            required_parameters=("window",),
            resolve_minimum_observations=lambda parameters: int(parameters["window"]),
        )
    )
    register_operation(
        OperationSpec(
            name="rolling_std",
            operation_id="qlibx.alpha.rolling_std",
            version="1",
            axis="time_by_ticker",
            tie_behavior="not_applicable",
            nan_behavior="full_window_required",
            minimum_observations=None,
            group_missing_behavior="not_applicable",
            dtype="float64",
            summary="Trailing standard deviation over a full window of index positions.",
            apply=rolling_std,
            parameters={
                "window": "positive number of trailing index positions",
                "ddof": "delta degrees of freedom in [0, window)",
            },
            required_parameters=("window",),
            resolve_minimum_observations=lambda parameters: int(parameters["window"]),
        )
    )
    register_operation(
        OperationSpec(
            name="linear_decay",
            operation_id="qlibx.alpha.linear_decay",
            version="1",
            axis="time_by_ticker",
            tie_behavior="not_applicable",
            nan_behavior="full_window_required",
            minimum_observations=None,
            group_missing_behavior="not_applicable",
            dtype="float64",
            summary="Linearly weighted trailing average with the newest observation heaviest.",
            apply=linear_decay,
            parameters={"window": "positive number of trailing index positions"},
            required_parameters=("window",),
            resolve_minimum_observations=lambda parameters: int(parameters["window"]),
        )
    )
    register_operation(
        OperationSpec(
            name="hump",
            operation_id="qlibx.alpha.hump",
            version="1",
            axis="time_by_ticker",
            tie_behavior="not_applicable",
            nan_behavior="preserve_without_fill_and_restart_after_gap",
            minimum_observations=1,
            group_missing_behavior="not_applicable",
            dtype="float64",
            summary="Bound each ticker's step change; a gap restarts the limiter.",
            apply=hump,
            parameters={"maximum_change": "non-negative maximum absolute step change"},
            required_parameters=("maximum_change",),
        )
    )
    register_operation(
        OperationSpec(
            name="top_bottom",
            operation_id="qlibx.alpha.top_bottom",
            version="1",
            axis="date_by_ticker",
            tie_behavior="first_by_column_order",
            nan_behavior="preserve",
            minimum_observations=2,
            group_missing_behavior="not_applicable",
            dtype="float64",
            summary="Select the highest names as +1 and the lowest as -1; others are 0.",
            apply=top_bottom,
            parameters={"count": "positive number of names selected on each side"},
            required_parameters=("count",),
            selection_behavior="disjoint_sides_required; fewer than 2*count valid names fails",
            resolve_minimum_observations=lambda parameters: 2 * int(parameters["count"]),
        )
    )
    register_operation(
        OperationSpec(
            name="per_name_cap",
            operation_id="qlibx.alpha.per_name_cap",
            version="1",
            axis="date_by_ticker",
            tie_behavior="not_applicable",
            nan_behavior="preserve",
            minimum_observations=1,
            group_missing_behavior="not_applicable",
            dtype="float64",
            summary="Bound each name's absolute weight without changing sign or missingness.",
            apply=per_name_cap,
            parameters={"maximum_weight": "positive maximum absolute per-name weight"},
            required_parameters=("maximum_weight",),
        )
    )


_register_builtins()

# Backwards-compatible read-only view of the declared semantics.
OPERATION_CONTRACTS: Mapping[str, Mapping[str, Any]] = {
    spec["name"]: spec for spec in OPERATIONS.describe()
}


# --------------------------------------------------------------------------------------
# Dispatch and composition
# --------------------------------------------------------------------------------------


def operation_contract(name: str, **parameters: Any) -> OperationContract:
    """Return the versioned semantics that become transform lineage."""
    return OPERATIONS.get(name).contract(parameters)


def _validate_parameters(spec: OperationSpec, parameters: Mapping[str, Any]) -> None:
    unknown = sorted(set(parameters) - set(spec.parameters))
    if unknown:
        raise ValueError(
            f"operation {spec.name} does not accept parameters {unknown}; "
            f"declared: {sorted(spec.parameters)}"
        )
    missing = sorted(set(spec.required_parameters) - set(parameters))
    if missing:
        raise ValueError(f"operation {spec.name} requires parameters {missing}")


def _apply_spec(
    spec: OperationSpec,
    values: pd.DataFrame,
    groups: pd.DataFrame | None,
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    _validate_parameters(spec, parameters)
    if spec.requires_groups:
        if groups is None:
            raise ValueError(f"{spec.name} requires explicit groups")
        return spec.apply(values, groups=groups, **parameters)
    return spec.apply(values, **parameters)


def apply_transform(
    name: str,
    values: pd.DataFrame,
    *,
    groups: pd.DataFrame | None = None,
    **parameters: Any,
) -> TransformResult:
    """Apply one registered operation and return its explicit lineage."""
    spec = OPERATIONS.get(name)
    transformed = _apply_spec(spec, values, groups, parameters)
    return TransformResult(transformed, (spec.contract(parameters),), spec.neutrality_warning)


@dataclass(frozen=True, slots=True)
class PipelineStep:
    name: str
    parameters: Mapping[str, Any] = field(default_factory=dict)


StepLike = PipelineStep | str | tuple[str, Mapping[str, Any]]


def _as_step(step: StepLike) -> PipelineStep:
    if isinstance(step, PipelineStep):
        return step
    if isinstance(step, str):
        return PipelineStep(step)
    name, parameters = step
    return PipelineStep(name, dict(parameters))


def apply_pipeline(
    values: pd.DataFrame,
    steps: Sequence[StepLike] | Iterable[StepLike],
    *,
    groups: pd.DataFrame | None = None,
) -> TransformResult:
    """Compose registered operations in order and accumulate one lineage chain.

    Every step contributes its own ``OperationContract``, so a chained result records
    exactly which operations, versions, and parameters produced it.
    """
    ordered = [_as_step(step) for step in steps]
    if not ordered:
        raise ValueError("pipeline requires at least one step")
    current = values
    lineage: list[OperationContract] = []
    warnings: list[str] = []
    for step in ordered:
        spec = OPERATIONS.get(step.name)
        current = _apply_spec(spec, current, groups, step.parameters)
        lineage.append(spec.contract(step.parameters))
        if spec.neutrality_warning is not None and spec.neutrality_warning not in warnings:
            warnings.append(spec.neutrality_warning)
    return TransformResult(current, tuple(lineage), " ".join(warnings) if warnings else None)


# --------------------------------------------------------------------------------------
# Budget (weight-scaling) policies
# --------------------------------------------------------------------------------------


SideScales = tuple[pd.Series, pd.Series]


@dataclass(frozen=True, slots=True)
class BudgetPolicySpec:
    """One weight-scaling rule.

    ``resolve`` receives the per-date realized side exposure and the declared side
    budgets, and returns the ``(long_scale, short_scale)`` applied to each side. A
    missing scale means the side has no candidates and collapses to zero.
    """

    name: str
    policy_id: str
    version: str
    summary: str
    unused_budget_behavior: str
    resolve: Callable[[pd.Series, pd.Series, float, float], SideScales]

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "policy_id": self.policy_id,
            "version": self.version,
            "summary": self.summary,
            "unused_budget_behavior": self.unused_budget_behavior,
        }


class BudgetPolicyRegistry:
    """Name-to-``BudgetPolicySpec`` registry backing every weight-scaling call."""

    def __init__(self) -> None:
        self._policies: dict[str, BudgetPolicySpec] = {}

    def register(
        self, spec: BudgetPolicySpec, *, replace_existing: bool = False
    ) -> BudgetPolicySpec:
        if spec.name in self._policies and not replace_existing:
            raise ValueError(f"budget policy is already registered: {spec.name}")
        self._policies[spec.name] = spec
        return spec

    def unregister(self, name: str) -> None:
        self._policies.pop(name, None)

    def get(self, name: str) -> BudgetPolicySpec:
        try:
            return self._policies[name]
        except KeyError as error:
            raise unknown_name(
                "QLIBX_BUDGET_POLICY_UNKNOWN", "budget policy", name, self._policies
            ) from error

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._policies))

    def describe(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._policies[name].describe() for name in self.names())


BUDGET_POLICIES = BudgetPolicyRegistry()


def register_budget_policy(
    spec: BudgetPolicySpec, *, replace_existing: bool = False
) -> BudgetPolicySpec:
    """Register a project-local weight-scaling rule alongside the built-ins."""
    return BUDGET_POLICIES.register(spec, replace_existing=replace_existing)


def budget_policy(name: str) -> BudgetPolicySpec:
    return BUDGET_POLICIES.get(name)


def list_budget_policies() -> tuple[dict[str, Any], ...]:
    return BUDGET_POLICIES.describe()


def _side_scales(
    long_sum: pd.Series,
    short_sum: pd.Series,
    long_budget: float,
    short_budget: float,
) -> SideScales:
    return (
        long_budget / long_sum.replace(0.0, pd.NA),
        short_budget / short_sum.replace(0.0, pd.NA),
    )


def _fixed(
    long_sum: pd.Series,
    short_sum: pd.Series,
    long_budget: float,
    short_budget: float,
) -> SideScales:
    return _side_scales(long_sum, short_sum, long_budget, short_budget)


def _flexible(
    long_sum: pd.Series,
    short_sum: pd.Series,
    long_budget: float,
    short_budget: float,
) -> SideScales:
    long_scale, short_scale = _side_scales(long_sum, short_sum, long_budget, short_budget)
    return long_scale.clip(upper=1.0), short_scale.clip(upper=1.0)


BUDGET_POLICIES.register(
    BudgetPolicySpec(
        name="fixed",
        policy_id="qlibx.alpha.budget.fixed",
        version="1",
        summary="Scale each side to exactly its declared budget when candidates exist.",
        unused_budget_behavior="each side with candidates is scaled up to its full budget",
        resolve=_fixed,
    )
)
BUDGET_POLICIES.register(
    BudgetPolicySpec(
        name="flexible",
        policy_id="qlibx.alpha.budget.flexible",
        version="1",
        summary="Treat each side budget as a maximum and never scale a side upward.",
        unused_budget_behavior="unused budget is preserved and reported as leftover",
        resolve=_flexible,
    )
)


@dataclass(frozen=True, slots=True)
class BudgetResult:
    """Rescaled weights plus the leftover budget each side did not use."""

    weights: pd.DataFrame
    policy_id: str
    policy_version: str
    long_budget: float
    short_budget: float
    long_used: pd.Series
    short_used: pd.Series
    long_leftover: pd.Series
    short_leftover: pd.Series


def apply_budget(
    weights: pd.DataFrame,
    *,
    policy: str = "fixed",
    long_budget: float = 1.0,
    short_budget: float = 1.0,
) -> BudgetResult:
    """Apply a registered weight-scaling policy and report the leftover budget."""
    if long_budget < 0 or short_budget < 0:
        raise ValueError("side budgets must be non-negative")
    spec = BUDGET_POLICIES.get(policy)
    positive = weights.clip(lower=0.0)
    negative = weights.clip(upper=0.0)
    long_sum = positive.sum(axis=1)
    short_sum = -negative.sum(axis=1)
    long_scale, short_scale = spec.resolve(long_sum, short_sum, long_budget, short_budget)
    result = positive.mul(long_scale.fillna(0.0), axis=0)
    result += negative.mul(short_scale.fillna(0.0), axis=0)
    result = result.where(weights.notna(), pd.NA)
    long_used = result.clip(lower=0.0).sum(axis=1)
    short_used = -result.clip(upper=0.0).sum(axis=1)
    return BudgetResult(
        weights=result,
        policy_id=spec.policy_id,
        policy_version=spec.version,
        long_budget=float(long_budget),
        short_budget=float(short_budget),
        long_used=long_used,
        short_used=short_used,
        long_leftover=(long_budget - long_used).clip(lower=0.0),
        short_leftover=(short_budget - short_used).clip(lower=0.0),
    )


def rescale_budget(
    weights: pd.DataFrame,
    *,
    mode: str = "fixed",
    long_budget: float = 1.0,
    short_budget: float = 1.0,
) -> pd.DataFrame:
    """Apply explicit side budgets; flexible mode never scales a side upward."""
    return apply_budget(
        weights,
        policy=mode,
        long_budget=long_budget,
        short_budget=short_budget,
    ).weights


# --------------------------------------------------------------------------------------
# Exposure measurement
# --------------------------------------------------------------------------------------


def exposure_summary(weights: pd.DataFrame) -> ExposureSummary:
    long = weights.clip(lower=0.0).sum(axis=1)
    short = weights.clip(upper=0.0).sum(axis=1)
    gross = long - short
    net = long + short
    coverage = weights.notna().sum(axis=1)
    missingness = weights.isna().mean(axis=1)
    return ExposureSummary(long, short, gross, net, coverage, missingness)


def analyze_exposure(
    weights: pd.DataFrame,
    *,
    input_id: str,
    dataset_ids: Mapping[str, str],
    method: str,
    market_beta: pd.DataFrame | None = None,
    benchmark_beta: pd.DataFrame | None = None,
    groups: pd.DataFrame | None = None,
    factors: Mapping[str, pd.DataFrame] | None = None,
    realized_holdings: pd.DataFrame | None = None,
    analyzer_id: str = "qlibx.alpha.exposure",
    analyzer_version: str = "1",
) -> ExposureArtifact:
    """Measure declared exposures without claiming exact neutrality."""
    if weights.empty:
        raise ValueError("exposure analysis requires at least one row")
    summary = exposure_summary(weights)
    market = _weighted_exposure(weights, market_beta, "market_beta")
    benchmark = _weighted_exposure(weights, benchmark_beta, "benchmark_beta")
    group = _group_exposure(weights, groups) if groups is not None else None
    factor = None
    if factors:
        columns = {
            name: _weighted_exposure(weights, values, f"factor {name}")
            for name, values in factors.items()
        }
        factor = pd.DataFrame(columns, index=weights.index)
    gap = None
    if realized_holdings is not None:
        intended, realized = weights.align(realized_holdings, join="outer")
        gap = exposure_summary(realized.sub(intended))
    return ExposureArtifact(
        analyzer_id=analyzer_id,
        analyzer_version=analyzer_version,
        input_id=input_id,
        dataset_ids=dict(dataset_ids),
        estimation_window=(str(weights.index.min()), str(weights.index.max())),
        method=method,
        summary=summary,
        market_exposure=market,
        benchmark_exposure=benchmark,
        group_exposure=group,
        factor_exposure=factor,
        intended_realized_gap=gap,
        coverage=summary.coverage,
        missingness=summary.missingness,
        neutrality_warning=NEUTRALITY_WARNING,
    )


def _weighted_exposure(
    weights: pd.DataFrame,
    exposures: pd.DataFrame | None,
    label: str,
) -> pd.Series | None:
    if exposures is None:
        return None
    aligned_weights, aligned_exposures = weights.align(exposures, join="left")
    if not aligned_exposures.index.equals(weights.index):
        raise ValueError(f"{label} index is incompatible with weights")
    return aligned_weights.mul(aligned_exposures).sum(axis=1, min_count=1)


def _group_exposure(weights: pd.DataFrame, groups: pd.DataFrame) -> pd.DataFrame:
    aligned_weights, aligned_groups = weights.align(groups, join="left")
    labels = sorted({str(value) for value in aligned_groups.to_numpy().ravel() if pd.notna(value)})
    output = pd.DataFrame(0.0, index=aligned_weights.index, columns=labels)
    for date in aligned_weights.index:
        row = aligned_weights.loc[date]
        row_groups = aligned_groups.loc[date]
        for label in labels:
            members = row_groups.astype("string").eq(label)
            output.loc[date, label] = row.where(members).sum(min_count=1)
    return output


__all__ = [
    "BUDGET_POLICIES",
    "NEUTRALITY_WARNING",
    "OPERATIONS",
    "OPERATION_CONTRACTS",
    "BudgetPolicyRegistry",
    "BudgetPolicySpec",
    "BudgetResult",
    "ExposureArtifact",
    "ExposureSummary",
    "OperationContract",
    "OperationRegistry",
    "OperationSpec",
    "PipelineStep",
    "TransformResult",
    "analyze_exposure",
    "apply_budget",
    "apply_pipeline",
    "apply_transform",
    "budget_policy",
    "clip",
    "cross_sectional_demean",
    "cross_sectional_rank",
    "cross_sectional_zscore",
    "exposure_summary",
    "group_demean",
    "hump",
    "lag",
    "linear_decay",
    "list_budget_policies",
    "list_operations",
    "operation_contract",
    "operation_spec",
    "per_name_cap",
    "register_budget_policy",
    "register_operation",
    "rescale_budget",
    "rolling_mean",
    "rolling_std",
    "top_bottom",
    "winsorize",
]
