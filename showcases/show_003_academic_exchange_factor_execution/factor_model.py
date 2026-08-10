"""Showcase-local cross-sectional factor model using public qlibx contracts."""

import math
from dataclasses import dataclass
from typing import ClassVar

import pandas as pd

from qlibx import (
    ArtifactSemanticConstraint,
    BudgetMode,
    ComponentRequirement,
    DecisionAction,
    MaterializeView,
    RowsLookback,
    StoredSignalEntry,
    StoredSignalResult,
    StrategyArtifactRequirement,
    StrategyDraft,
    StrategyView,
    WeightEntry,
)
from qlibx.operations import (
    MaterializationComputationError,
    MaterializationOutputContract,
)

STORED_SIGNAL_OUTPUT = MaterializationOutputContract(
    artifact_type="stored_signal_result",
    artifact_schema_version=1,
    payload_model=StoredSignalResult,
)


@dataclass(frozen=True, slots=True)
class MonthlyReversalModel:
    """Materialize negative trailing return as one frozen cross-sectional signal."""

    dataset_id: str
    lookback_sessions: int = 20
    producer_id: str = "showcase.monthly-reversal.v1"

    output_contract: ClassVar[MaterializationOutputContract[StoredSignalResult]] = (
        STORED_SIGNAL_OUTPUT
    )

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return (
            ComponentRequirement(
                requirement_id="showcase.factor.input_return",
                semantic_role="factor_input_return",
                dataset_id=self.dataset_id,
                lookback=RowsLookback(rows=self.lookback_sessions),
            ),
        )

    def run(self, view: MaterializeView) -> StoredSignalResult:
        frame = view.history("factor_input_return")
        values = pd.to_numeric(frame["factor_input_return"], errors="coerce")
        usable = frame.assign(factor_input_return=values).loc[values.notna()].copy()
        decision_time = pd.Timestamp(view.as_of).tz_convert("UTC")
        entries: list[StoredSignalEntry] = []
        invalid: list[dict[str, object]] = []
        for instrument, group in usable.groupby("instrument", sort=True):
            window = group.sort_values("observation_time", kind="mergesort").tail(
                self.lookback_sessions
            )
            observations = pd.to_datetime(window["observation_time"], utc=True)
            returns = window["factor_input_return"].astype(float)
            if (
                len(window) != self.lookback_sessions
                or observations.max() != decision_time
                or not all(math.isfinite(value) and value > -1 for value in returns)
            ):
                invalid.append({"instrument": str(instrument), "rows": len(window)})
                continue
            trailing_return = math.prod(1 + value for value in returns) - 1
            entries.append(
                StoredSignalEntry(instrument=str(instrument), value=-trailing_return)
            )
        if invalid or len(entries) < 4:
            raise MaterializationComputationError(
                "SHOWCASE_FACTOR_COVERAGE_INVALID",
                "each instrument requires a complete window ending at the decision",
                context={"invalid": invalid[:20], "valid_instruments": len(entries)},
            )
        return StoredSignalResult(
            signal_semantics=(
                f"negative_compounded_close_return_{self.lookback_sessions}_complete_sessions"
            ),
            observation_time=view.as_of,
            entries=tuple(entries),
        )


@dataclass(frozen=True, slots=True)
class DemeanedUnitGrossStrategy:
    """Turn one exact stored signal into signed unit-gross alpha weights."""

    signal_semantics: str
    strategy_id: str = "showcase.monthly-reversal.signed-portfolio.v1"

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return ()

    def artifact_requirements(self) -> tuple[StrategyArtifactRequirement, ...]:
        return (
            StrategyArtifactRequirement(
                requirement_id="showcase.portfolio.stored-signal",
                consumer_role="stored_signal",
                artifact_type="stored_signal_result",
                artifact_schema_version=1,
                semantic_constraints=(
                    ArtifactSemanticConstraint(
                        field="signal_semantics",
                        expected=self.signal_semantics,
                    ),
                ),
            ),
        )

    def run(self, view: StrategyView) -> StrategyDraft:
        signal = view.artifact("stored_signal", StoredSignalResult)
        values = pd.Series(
            {entry.instrument: float(entry.value) for entry in signal.entries},
            dtype="float64",
        ).sort_index()
        centered = values - values.mean()
        gross = float(centered.abs().sum())
        if len(centered) < 2 or not math.isfinite(gross) or gross <= 0:
            raise ValueError("demeaned unit-gross weighting requires varying finite signals")
        weights = centered / gross
        return StrategyDraft(
            weights=tuple(
                WeightEntry(instrument=str(instrument), weight=float(weight))
                for instrument, weight in weights.items()
            ),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
            diagnostics=("cross-sectional demean and normalize to unit gross",),
        )
