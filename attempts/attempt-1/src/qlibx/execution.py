"""Public stored-alpha, ensemble, reporting, and Qlib execution use cases.

The matched-capitalization path is a compatibility mode for Qlib's long-only
account model. It does not provide native borrow, margin, recall, or borrow-fee
modeling.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from ._vendor.qlib_backend.backend import (
    MatchedCapitalizationInputs,
    QlibClosedLoopBackend,
    ResumeState,
)
from ._vendor.qlib_engine import (
    ConfigurationError,
    build_enhanced_index_attribution,
    build_ensemble,
    build_signed_attribution,
    create_report,
    run_strategy_batch,
)
from .errors import QlibxError, QlibxInternalError, unknown_name
from .run_catalog import RunCatalog, open_run_catalog
from .strategy import (
    DecisionContext,
    DecisionProgram,
    DecisionResult,
    FeedbackEvent,
    StrategyDefinition,
    run_decision,
)


@dataclass(frozen=True, slots=True)
class ExecutionScenario:
    """The market inputs the Qlib backend reads, declared in exactly one place.

    The backend consumes this by attribute. Naming the fields here turns an implicit
    duck-typed boundary into a checked one: a renamed or forgotten field fails at
    construction instead of surfacing as a missing attribute deep inside a backtest.
    """

    execution_price: pd.DataFrame
    valuation_price: pd.DataFrame
    universe: pd.DataFrame
    booksize: float
    active_booksize: float
    position_unit_factor: pd.DataFrame
    volume: pd.DataFrame
    buyable: pd.DataFrame
    sellable: pd.DataFrame
    asset_class: pd.Series
    lot_size: pd.Series
    cost_policy: Mapping[str, Mapping[str, float]] | None
    max_volume_participation: float
    suspended: pd.DataFrame | None = None
    upper_price_limit: pd.DataFrame | None = None
    lower_price_limit: pd.DataFrame | None = None


def _build_scenario(
    *,
    execution_price: pd.DataFrame,
    valuation_price: pd.DataFrame,
    universe: pd.DataFrame,
    volume: pd.DataFrame,
    initial_cash: float,
    active_booksize: float | None,
    position_unit_factor: pd.DataFrame | None,
    tradable: pd.DataFrame | None,
    instrument_type: pd.Series | None,
    lot_size: pd.Series | None,
    cost_policy: Mapping[str, Mapping[str, float]] | None,
    max_volume_participation: float,
) -> ExecutionScenario:
    """Apply the documented defaults for every optional market input."""
    instruments = execution_price.columns
    available = (
        pd.DataFrame(True, index=execution_price.index, columns=instruments)
        if tradable is None
        else tradable
    )
    return ExecutionScenario(
        execution_price=execution_price,
        valuation_price=valuation_price,
        universe=universe,
        booksize=float(initial_cash),
        active_booksize=float(initial_cash if active_booksize is None else active_booksize),
        position_unit_factor=(
            pd.DataFrame(1.0, index=execution_price.index, columns=instruments)
            if position_unit_factor is None
            else position_unit_factor
        ),
        volume=volume,
        buyable=available,
        sellable=available,
        asset_class=(
            pd.Series("stock", index=instruments)
            if instrument_type is None
            else instrument_type.reindex(instruments)
        ),
        lot_size=(
            pd.Series(1, index=instruments) if lot_size is None else lot_size.reindex(instruments)
        ),
        cost_policy=cost_policy,
        max_volume_participation=max_volume_participation,
    )


@dataclass(frozen=True, slots=True)
class SignedExecutionResult:
    mode: str
    compatibility_limitations: tuple[str, ...]
    intended_weights: pd.DataFrame
    orders: pd.DataFrame
    fills: pd.DataFrame
    signed_positions: pd.DataFrame
    composite_account: pd.DataFrame
    baseline_account: pd.DataFrame
    active_account: pd.DataFrame
    capitalization_events: pd.DataFrame
    reconciliation: Mapping[str, float | bool]
    checkpoint: Mapping[str, Any]
    evidence: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class SignedExecutionConfig:
    """Matched-capitalization settings for an adaptive signed StrategyAgent."""

    observed: pd.DataFrame
    shortable: pd.DataFrame
    active_booksize: float
    per_name_short_cap: float = 0.3
    safety_multiplier: float = 1.0
    inventory_retention: str = "retained"


@dataclass(frozen=True, slots=True)
class StrategyExecutionCheckpoint:
    qlib_state: Mapping[str, Any]
    memory: Mapping[str, Any]
    feedback_history: tuple[FeedbackEvent, ...]
    previous_result_id: str | None


@dataclass(frozen=True, slots=True)
class StrategyExecutionResult:
    mode: str
    decisions: tuple[DecisionResult, ...]
    orders: pd.DataFrame
    fills: pd.DataFrame
    positions: pd.DataFrame
    account: pd.DataFrame
    signed: SignedExecutionResult | None
    feedback_audit: pd.DataFrame
    checkpoint: StrategyExecutionCheckpoint
    evidence: Mapping[str, Any]


def run_strategy_execution(
    definition: StrategyDefinition,
    program: DecisionProgram,
    *,
    datasets: Mapping[str, pd.DataFrame],
    execution_price: pd.DataFrame,
    valuation_price: pd.DataFrame,
    universe: pd.DataFrame,
    volume: pd.DataFrame,
    initial_cash: float,
    availability: Mapping[str, pd.DataFrame | pd.Series] | None = None,
    dataset_ids: Mapping[str, str] | None = None,
    lookback_rows: Mapping[str, int] | None = None,
    position_unit_factor: pd.DataFrame | None = None,
    tradable: pd.DataFrame | None = None,
    instrument_type: pd.Series | None = None,
    lot_size: pd.Series | None = None,
    cost_policy: Mapping[str, Mapping[str, float]] | None = None,
    max_volume_participation: float = 1.0,
    effective_config_id: str = "",
    start_position: int = 0,
    end_position: int | None = None,
    checkpoint: StrategyExecutionCheckpoint | None = None,
    signed: SignedExecutionConfig | None = None,
) -> StrategyExecutionResult:
    """Run long-only or signed weights inside Qlib's confirmed-feedback loop."""
    if definition.output_kind != "weight":
        raise QlibxError(
            "EXECUTION",
            f"Qlib execution needs a weight output, but the Strategy declares "
            f"{definition.output_kind!r}",
            expected="Declare output_kind 'weight' on the Strategy, or use a signal workflow.",
            context={"output_kind": definition.output_kind},
        )
    instruments = execution_price.columns
    scenario = _build_scenario(
        execution_price=execution_price,
        valuation_price=valuation_price,
        universe=universe,
        volume=volume,
        initial_cash=initial_cash,
        active_booksize=None if signed is None else signed.active_booksize,
        position_unit_factor=position_unit_factor,
        tradable=tradable,
        instrument_type=instrument_type,
        lot_size=lot_size,
        cost_policy=cost_policy,
        max_volume_participation=max_volume_participation,
    )
    memory: Mapping[str, Any] = {} if checkpoint is None else dict(checkpoint.memory)
    feedback_history = [] if checkpoint is None else list(checkpoint.feedback_history)
    previous_result_id = None if checkpoint is None else checkpoint.previous_result_id
    decisions: list[DecisionResult] = []
    adaptive_weights: dict[pd.Timestamp, pd.Series] = {}
    availability_by_dataset = dict(availability or {})
    ids = dict(dataset_ids or {})
    lookbacks = dict(lookback_rows or {})

    def target_policy(date: pd.Timestamp, state: Mapping[str, Any]) -> pd.Series:
        nonlocal memory, previous_result_id
        _append_confirmed_feedback(feedback_history, state)
        if "universe" in datasets:
            raise QlibxError(
                "EXECUTION",
                "universe is inherited from the execution scenario and cannot be passed again",
                expected="Remove 'universe' from datasets; the scenario universe is authoritative.",
                context={"datasets": sorted(datasets)},
            )
        strategy_datasets = {"universe": universe, **datasets}
        bounded, bounded_availability = _bounded_strategy_data(
            strategy_datasets,
            availability_by_dataset,
            pd.Timestamp(date),
            lookbacks,
        )
        if signed is None:
            account = {
                "held_quantity": state["current_physical_quantity"],
                "weight": state["current_physical_weight"],
                "physical_quantity": state["current_physical_quantity"],
                "physical_weight": state["current_physical_weight"],
                "cash_weight": state["current_cash_weight"],
                "nav": state["current_nav"],
            }
        else:
            account = {
                "held_quantity": state["current_signed_quantity"],
                "weight": state["current_signed_weight"],
                "signed_quantity": state["current_signed_quantity"],
                "signed_weight": state["current_signed_weight"],
                "physical_quantity": state["current_physical_quantity"],
                "physical_weight": state["current_physical_weight"],
                "baseline_quantity": state["current_baseline_quantity"],
                "cash_weight": state["current_cash_weight"],
                "nav": state["current_nav"],
                "composite_nav": state["current_composite_nav"],
            }
        last_feedback = feedback_history[-1].payload if feedback_history else {}
        context = DecisionContext(
            pd.Timestamp(date),
            bounded,
            feedback=last_feedback,
            memory=memory,
            seed=0,
            availability=bounded_availability,
            dataset_ids=ids,
            lookbacks={name: f"last_{rows}_available_rows" for name, rows in lookbacks.items()},
            feedback_history=tuple(feedback_history),
            account=account,
        )
        result = run_decision(
            definition,
            program,
            context,
            effective_config_id=effective_config_id,
            dependency_versions={"qlib": "0.9.7"},
        )
        target = _weight_payload(result.payload, instruments)
        if signed is None and (
            target.isna().any() or target.lt(-1e-12).any() or target.sum() > 1.0 + 1e-12
        ):
            raise QlibxError(
                "EXECUTION",
                "Long-only weight output must be finite, non-negative, and sum to at most 1",
                expected="Clip or renormalize the Strategy weights before returning them.",
                context={
                    "decision_time": str(date),
                    "weight_sum": float(target.sum()),
                    "has_missing": bool(target.isna().any()),
                    "minimum_weight": float(target.min()),
                },
            )
        if signed is not None:
            long_exposure = float(target.clip(lower=0.0).sum())
            short_exposure = float(-target.clip(upper=0.0).sum())
            if long_exposure > 1.0 + 1e-12 or short_exposure > 1.0 + 1e-12:
                raise QlibxError(
                    "EXECUTION",
                    "Signed side exposure must not exceed 1 on either side",
                    expected="Scale the signed weights with a budget policy before execution.",
                    context={
                        "decision_time": str(date),
                        "long_exposure": long_exposure,
                        "short_exposure": short_exposure,
                    },
                )
            adaptive_weights[pd.Timestamp(date)] = target.copy()
        decisions.append(result)
        memory = dict(result.memory)
        previous_result_id = result.result_id
        return target

    restored = None if checkpoint is None else ResumeState(**dict(checkpoint.qlib_state))
    matched = (
        None
        if signed is None
        else MatchedCapitalizationInputs(
            signed_weights=None,
            observed=signed.observed,
            shortable=signed.shortable,
            per_name_short_cap=signed.per_name_short_cap,
            safety_multiplier=signed.safety_multiplier,
            inventory_retention=signed.inventory_retention,
        )
    )
    backend = QlibClosedLoopBackend().run_targets(
        scenario,
        pd.DataFrame(0.0, index=execution_price.index, columns=instruments),
        target_policy=(target_policy if signed is None else None),
        signed_target_policy=(target_policy if signed is not None else None),
        matched_capitalization=matched,
        start_position=start_position,
        end_position=end_position,
        resume_state=restored,
    )
    _append_final_feedback(feedback_history, backend, signed=signed is not None)
    qlib_state = asdict(backend.evidence["resume_state"])
    signed_result = None
    positions = backend.positions()
    account = backend.account_daily()
    if signed is not None:
        intended = pd.DataFrame.from_dict(adaptive_weights, orient="index").reindex(
            columns=instruments
        )
        intended.index = pd.DatetimeIndex(intended.index, name=execution_price.index.name)
        signed_result = _signed_result_from_backend(backend, intended)
        positions = signed_result.signed_positions
        account = signed_result.active_account
    return StrategyExecutionResult(
        mode="long_only" if signed is None else "matched_capitalization",
        decisions=tuple(decisions),
        orders=backend.orders(),
        fills=backend.fills(),
        positions=positions,
        account=account,
        signed=signed_result,
        feedback_audit=backend.feedback_audit(),
        checkpoint=StrategyExecutionCheckpoint(
            qlib_state,
            memory,
            tuple(feedback_history),
            previous_result_id,
        ),
        evidence={
            **backend.backend_evidence(),
            "strategy_id": definition.strategy_id,
            "decision_count": len(decisions),
            "feedback_order": "previous_qlib_confirmed_only",
            "decision_semantics": "physical_weight" if signed is None else "signed_weight",
        },
    )


def run_signed_execution(
    *,
    signed_weights: pd.DataFrame,
    execution_price: pd.DataFrame,
    valuation_price: pd.DataFrame,
    universe: pd.DataFrame,
    observed: pd.DataFrame,
    tradable: pd.DataFrame,
    shortable: pd.DataFrame,
    volume: pd.DataFrame,
    initial_cash: float,
    active_booksize: float,
    position_unit_factor: pd.DataFrame | None = None,
    instrument_type: pd.Series | None = None,
    lot_size: pd.Series | None = None,
    cost_policy: Mapping[str, Mapping[str, float]] | None = None,
    max_volume_participation: float = 1.0,
    per_name_short_cap: float = 0.3,
    safety_multiplier: float = 1.0,
    inventory_retention: str = "retained",
    start_position: int = 0,
    end_position: int | None = None,
    resume_state: Mapping[str, Any] | None = None,
) -> SignedExecutionResult:
    """Execute signed intent through real Qlib orders using matched capitalization."""
    instruments = execution_price.columns
    scenario = _build_scenario(
        execution_price=execution_price,
        valuation_price=valuation_price,
        universe=universe,
        volume=volume,
        initial_cash=initial_cash,
        active_booksize=active_booksize,
        position_unit_factor=position_unit_factor,
        tradable=tradable,
        instrument_type=instrument_type,
        lot_size=lot_size,
        cost_policy=cost_policy,
        max_volume_participation=max_volume_participation,
    )
    matched = MatchedCapitalizationInputs(
        signed_weights=signed_weights,
        observed=observed,
        shortable=shortable,
        per_name_short_cap=per_name_short_cap,
        safety_multiplier=safety_multiplier,
        inventory_retention=inventory_retention,
    )
    placeholder = pd.DataFrame(0.0, index=execution_price.index, columns=instruments)
    restored = None if resume_state is None else ResumeState(**dict(resume_state))
    backend = QlibClosedLoopBackend().run_targets(
        scenario,
        placeholder,
        matched_capitalization=matched,
        start_position=start_position,
        end_position=end_position,
        resume_state=restored,
    )
    return _signed_result_from_backend(backend, signed_weights.copy())


def _signed_result_from_backend(
    backend: Any,
    intended_weights: pd.DataFrame,
) -> SignedExecutionResult:
    signed = backend.extra_tables["signed_positions"].copy()
    baseline = backend.extra_tables["baseline_account_daily"].copy()
    active = backend.extra_tables["active_account_daily"].copy()
    events = _normalize_capitalization_events(backend.extra_tables["capitalization_events"].copy())
    composite = backend.account_daily()
    identity_error = (
        signed["held_quantity"]
        .sub(signed["composite_quantity"].sub(signed["baseline_quantity"]))
        .abs()
        .max()
    )
    minimum_composite = signed["composite_quantity"].min()
    account = composite.reset_index(drop=True)
    nav_error = account["nav"].sub(baseline["nav"].add(active["nav"])).abs().max()
    event_nav_error = _capitalization_nav_error(events)
    tolerance = 1e-8
    if identity_error > tolerance or minimum_composite < -tolerance:
        raise QlibxInternalError(
            "Signed quantity identity C = B + A does not hold within tolerance",
            context={
                "quantity_identity_max_error": float(identity_error),
                "minimum_composite_quantity": float(minimum_composite),
                "tolerance": tolerance,
            },
        )
    if nav_error > tolerance or event_nav_error > tolerance:
        raise QlibxInternalError(
            "Matched capitalization NAV identity composite = baseline + active does not hold",
            context={
                "account_nav_max_error": float(nav_error),
                "capitalization_nav_max_error": float(event_nav_error),
                "tolerance": tolerance,
            },
        )
    checkpoint = asdict(backend.evidence["resume_state"])
    evidence = {
        **backend.backend_evidence(),
        "mode": "matched_capitalization",
        "compatibility_hack": True,
        "signed_quantity_source": "qlib_composite_dealt_quantity_minus_baseline",
    }
    return SignedExecutionResult(
        mode="matched_capitalization",
        compatibility_limitations=(
            "Qlib stock Account and Position remain long-only.",
            "No native borrow, locate, margin, recall, forced buy-in, or borrow-fee model.",
            "Baseline reserve is required and composite return is not signed active return.",
        ),
        intended_weights=intended_weights,
        orders=backend.orders(),
        fills=backend.fills(),
        signed_positions=signed,
        composite_account=composite,
        baseline_account=baseline,
        active_account=active,
        capitalization_events=events,
        reconciliation={
            "quantity_identity_max_error": float(identity_error),
            "minimum_composite_quantity": float(minimum_composite),
            "account_nav_max_error": float(nav_error),
            "capitalization_nav_max_error": float(event_nav_error),
            "passed": True,
        },
        checkpoint=checkpoint,
        evidence=evidence,
    )


def _capitalization_nav_error(events: pd.DataFrame) -> float:
    if events.empty:
        return 0.0
    direction = events["event_type"].map({"activation": 1.0, "top_up": 1.0, "release": -1.0})
    if direction.isna().any():
        observed = sorted(set(events.loc[direction.isna(), "event_type"].astype(str)))
        raise unknown_name(
            "EXECUTION",
            "capitalization event type",
            ", ".join(observed),
            ("activation", "release", "top_up"),
        )
    effect = events["cash_change"].add(
        events["quantity"].mul(events["execution_price"]).mul(direction)
    )
    return float(effect.abs().max())


def _normalize_capitalization_events(events: pd.DataFrame) -> pd.DataFrame:
    output = events.copy()
    output["trade_date"] = pd.to_datetime(output["trade_date"])
    for column in (
        "event_sequence",
        "quantity",
        "baseline_quantity_before",
        "baseline_quantity_after",
    ):
        output[column] = output[column].astype("int64")
    for column in (
        "execution_price",
        "cash_change",
        "baseline_cash_before",
        "baseline_cash_after",
    ):
        output[column] = output[column].astype("float64")
    return output


def _bounded_strategy_data(
    datasets: Mapping[str, pd.DataFrame],
    availability: Mapping[str, pd.DataFrame | pd.Series],
    decision_time: pd.Timestamp,
    lookbacks: Mapping[str, int],
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame | pd.Series]]:
    bounded: dict[str, pd.DataFrame] = {}
    bounded_availability: dict[str, pd.DataFrame | pd.Series] = {}
    for name, values in datasets.items():
        if name in availability:
            raw = availability[name]
            if isinstance(raw, pd.Series):
                matrix = pd.DataFrame(
                    {column: raw for column in values.columns},
                    index=values.index,
                )
            else:
                matrix = raw
            if not matrix.index.equals(values.index) or not matrix.columns.equals(values.columns):
                raise QlibxError(
                    "EXECUTION",
                    f"Availability matrix for {name!r} does not share the dataset's axes",
                    expected="Provide availability on exactly the dataset's index and columns.",
                    context={"dataset": name},
                )
            visible = matrix.apply(pd.to_datetime).le(decision_time)
            selected = values.where(visible)
            rows = selected.notna().any(axis=1)
            selected = selected.loc[rows]
            selected_availability = matrix.loc[rows]
            bounded_availability[name] = selected_availability
        else:
            if not isinstance(values.index, pd.DatetimeIndex):
                raise QlibxError(
                    "EXECUTION",
                    f"Dataset {name!r} has no DatetimeIndex, so availability must be declared",
                    expected=(
                        "Pass an availability matrix for this dataset; qlibx will not guess "
                        "when its observations became visible."
                    ),
                    context={"dataset": name},
                )
            selected = values.loc[values.index <= decision_time]
        count = lookbacks.get(name)
        if count is not None:
            if count < 1:
                raise QlibxError(
                    "EXECUTION",
                    f"lookback_rows for {name!r} must be positive, got {count}",
                    expected="Declare how many available rows the Strategy may read.",
                    context={"dataset": name, "lookback_rows": count},
                )
            selected = selected.tail(count)
            if name in bounded_availability:
                bounded_availability[name] = bounded_availability[name].loc[selected.index]
        bounded[name] = selected
    return bounded, bounded_availability


def _append_confirmed_feedback(
    feedback: list[FeedbackEvent],
    state: Mapping[str, Any],
) -> None:
    date = state.get("last_feedback_date")
    history = state.get("account_history", ())
    if date is None or not history:
        return
    timestamp = pd.Timestamp(date)
    if any(event.confirmed_at == timestamp for event in feedback):
        return
    row = history[-1]
    fills = [
        item
        for item in state.get("fill_history", ())
        if pd.Timestamp(item["trade_date"]) == timestamp
    ]
    feedback.append(
        FeedbackEvent(
            timestamp,
            "qlib_close",
            {
                "cash": float(row["cash"]),
                "nav": float(row["nav"]),
                "portfolio_return": float(row["portfolio_return"]),
                "fills": fills,
            },
        )
    )


def _append_final_feedback(
    feedback: list[FeedbackEvent],
    backend: Any,
    *,
    signed: bool,
) -> None:
    account = backend.extra_tables["active_account_daily"] if signed else backend.account_daily()
    if signed and not account.empty:
        account = account.set_index("trade_date")
    if account.empty:
        return
    date = pd.Timestamp(account.index[-1])
    if any(event.confirmed_at == date for event in feedback):
        return
    row = account.iloc[-1]
    fills = backend.fills(date).to_dict(orient="records")
    feedback.append(
        FeedbackEvent(
            date,
            "qlib_close",
            {
                "cash": float(row["cash"]),
                "nav": float(row["nav"]),
                "portfolio_return": float(row["portfolio_return"]),
                "fills": fills,
            },
        )
    )


def _weight_payload(payload: Any, instruments: pd.Index) -> pd.Series:
    if isinstance(payload, pd.DataFrame):
        if len(payload) != 1:
            raise QlibxError(
                "EXECUTION",
                f"Weight DataFrame must hold exactly one decision row, got {len(payload)}",
                expected="Return only the row for the current decision time.",
                context={"rows": len(payload)},
            )
        result = payload.iloc[0]
    elif isinstance(payload, pd.Series):
        result = payload
    else:
        raise QlibxError(
            "EXECUTION",
            f"Weight payload must be a Series or one-row DataFrame, got {type(payload).__name__}",
            expected="Return pandas weights keyed by instrument.",
            context={"payload_type": type(payload).__name__},
        )
    unknown = result.index.difference(instruments)
    if len(unknown):
        raise QlibxError(
            "EXECUTION",
            f"Strategy returned instruments outside the execution universe: {unknown.tolist()}",
            expected="Restrict the weights to the instruments the execution scenario declares.",
            context={"unknown_instruments": unknown.tolist()},
        )
    return result.reindex(instruments).fillna(0.0).astype("float64")


__all__ = [
    "ConfigurationError",
    "RunCatalog",
    "SignedExecutionConfig",
    "SignedExecutionResult",
    "StrategyExecutionCheckpoint",
    "StrategyExecutionResult",
    "build_enhanced_index_attribution",
    "build_ensemble",
    "build_signed_attribution",
    "create_report",
    "open_run_catalog",
    "run_signed_execution",
    "run_strategy_batch",
    "run_strategy_execution",
]
