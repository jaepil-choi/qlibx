from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

import pandas as pd


@dataclass(frozen=True)
class MarketScenario:
    """Acceptance fixture input; production object model을 규정하지 않습니다."""

    execution_price: pd.DataFrame
    universe: pd.DataFrame
    booksize: float
    position_unit_factor: pd.DataFrame | None = None
    valuation_price: pd.DataFrame | None = None
    volume: pd.DataFrame | None = None
    buyable: pd.DataFrame | None = None
    sellable: pd.DataFrame | None = None
    asset_class: pd.Series | None = None
    lot_size: pd.Series | None = None
    data: Mapping[str, pd.DataFrame] | None = None
    cost_policy: Mapping[str, Mapping[str, float]] | None = None
    max_volume_participation: float | None = None
    suspended: pd.DataFrame | None = None
    upper_price_limit: pd.DataFrame | None = None
    lower_price_limit: pd.DataFrame | None = None


@dataclass(frozen=True)
class StrategyRunIdentity:
    run_id: str
    strategy_id: str
    strategy_name: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    definition_hash: str
    code_version: str
    input_fingerprint: str
    reuse_scope: str
    run_fingerprint: str | None = None


@dataclass(frozen=True)
class LinearConstraintInput:
    name: str
    coefficients: pd.Series
    lower: float | None = None
    upper: float | None = None
    soft_penalty: float | None = None
    cash_coefficient: float = 0.0


@dataclass(frozen=True)
class OptimizationScenario:
    desired_active_exposure: pd.Series
    benchmark_weight: pd.Series
    current_physical_weight: pd.Series
    current_cash_weight: float
    lookthrough_matrix: pd.DataFrame
    tradable: pd.Series
    lower_bounds: pd.Series
    upper_bounds: pd.Series
    transaction_cost: pd.Series
    constraints: tuple[LinearConstraintInput, ...] = ()
    turnover_penalty: float = 0.0
    risk_penalty: float = 0.0
    risk_covariance: pd.DataFrame | None = None
    cash_lower: float = 0.0
    cash_upper: float = 1.0
    solver: str = "CLARABEL"


@runtime_checkable
class OptimizationObservation(Protocol):
    status: str
    physical_target_weight: pd.Series | None
    cash_target_weight: float | None
    lookthrough_exposure: pd.Series | None
    constraint_diagnostics: tuple[Any, ...]
    validation_passed: bool
    solver_metadata: Mapping[str, Any]


@runtime_checkable
class RunObservation(Protocol):
    """Test-only normalized observation port returned by the adapter."""

    def decision_weight(self, date: pd.Timestamp, instrument: str) -> float: ...

    def selected_rule(self, date: pd.Timestamp) -> str | None: ...

    def position_quantity(self, date: pd.Timestamp, instrument: str) -> int: ...

    def cash(self, date: pd.Timestamp) -> float: ...

    def nav(self, date: pd.Timestamp) -> float: ...

    def portfolio_return(self, date: pd.Timestamp) -> float: ...

    def orders(self, date: pd.Timestamp | None = None) -> pd.DataFrame: ...

    def fills(self, date: pd.Timestamp | None = None) -> pd.DataFrame: ...

    def positions(self) -> pd.DataFrame: ...

    def account_daily(self) -> pd.DataFrame: ...

    def signals(self) -> pd.DataFrame: ...

    def observation_audit(self) -> pd.DataFrame: ...

    def research_evaluations(self) -> pd.DataFrame: ...

    def feedback_audit(self) -> pd.DataFrame: ...

    def state_audit(self) -> pd.DataFrame: ...

    def backend_evidence(self) -> Mapping[str, Any]: ...


@runtime_checkable
class ArtifactStoreHarness(Protocol):
    def write_run(
        self, identity: StrategyRunIdentity, run: RunObservation
    ) -> Mapping[str, Any]: ...

    def load_table(
        self, identity: StrategyRunIdentity, table_name: str
    ) -> pd.DataFrame: ...

    def load_reporting_bundle(
        self, identity: StrategyRunIdentity
    ) -> Mapping[str, pd.DataFrame]: ...

    def load_ensemble_input(
        self, identity: StrategyRunIdentity, artifact_name: str
    ) -> pd.DataFrame: ...


@runtime_checkable
class BackendHarness(Protocol):
    """Capability adapter. 실제 production class/signature와 독립적입니다."""

    def run_consecutive_loss_stop(
        self, scenario: MarketScenario, consecutive_losses: int
    ) -> RunObservation: ...

    def run_subscription_probe(
        self,
        scenario: MarketScenario,
        subscriptions: Mapping[str, int],
    ) -> RunObservation: ...

    def run_stateful_probe(self, scenario: MarketScenario) -> RunObservation: ...

    def run_universe_probe(
        self, scenario: MarketScenario, *, reentry_policy: str | None
    ) -> RunObservation: ...

    def run_weight_targets(
        self,
        scenario: MarketScenario,
        target_weights: pd.DataFrame,
        *,
        signals: Mapping[str, pd.DataFrame] | None = None,
    ) -> RunObservation: ...

    def run_target_policy_probe(
        self,
        scenario: MarketScenario,
        target_policy: Callable[[pd.Timestamp, Mapping[str, Any]], pd.Series],
    ) -> RunObservation: ...

    def run_cached_ensemble(
        self,
        scenario: MarketScenario,
        member_artifacts: Mapping[str, pd.DataFrame],
        *,
        etf_weight: float,
    ) -> RunObservation: ...

    def run_adaptive_rules(
        self,
        scenario: MarketScenario,
        candidate_rules: tuple[str, ...],
        *,
        lookback: int,
    ) -> RunObservation: ...

    def run_adaptive_model(
        self,
        scenario: MarketScenario,
        *,
        train_dataset: str,
        retrain_every: int,
    ) -> RunObservation: ...

    def resume_equivalence_probe(
        self, scenario: MarketScenario, checkpoint_dir: Path
    ) -> tuple[RunObservation, RunObservation]: ...

    def resume_from_checkpoint(
        self, scenario: MarketScenario, checkpoint_path: Path
    ) -> RunObservation: ...

    def artifact_store(self, root: Path) -> ArtifactStoreHarness: ...

    def strategy_invocation_count(self) -> int: ...

    def optimize_portfolio(
        self, scenario: OptimizationScenario
    ) -> OptimizationObservation: ...

    def run_optimizer_feedback_loop(
        self,
        scenario: MarketScenario,
        optimization: OptimizationScenario,
    ) -> RunObservation: ...
