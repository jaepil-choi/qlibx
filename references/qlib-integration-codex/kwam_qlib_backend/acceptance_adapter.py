from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from kwam_qlib_backend.constraint_optimization import (
    CvxpyIntentTrackingOptimizer,
    LinearConstraintSpec,
    OptimizationProblem,
    OptimizerConfig,
)

from .artifacts import ParquetArtifactStore
from .backend import QlibClosedLoopBackend, ResumeState
from .optimization import OptimizationTargetPolicy
from .result import BackendRunResult


CHECKPOINT_SCHEMA = "kwam-qlib-checkpoint-v2"


class AcceptanceHarness:
    """Test-only normalization adapter over the production Qlib backend."""

    def __init__(self) -> None:
        self._backend = QlibClosedLoopBackend()
        self._strategy_invocations = 0

    def run_consecutive_loss_stop(
        self, scenario: Any, consecutive_losses: int
    ) -> BackendRunResult:
        self._mark_invocation()
        if consecutive_losses <= 0:
            raise ValueError("consecutive_losses must be positive")
        columns = scenario.execution_price.columns
        placeholder = pd.DataFrame(
            1.0 / len(columns), index=scenario.execution_price.index, columns=columns
        )

        def policy(date: pd.Timestamp, feedback: Mapping[str, Any]) -> pd.Series:
            del date
            streak = 0
            for row in reversed(feedback["account_history"]):
                if float(row["portfolio_return"]) < -1e-12:
                    streak += 1
                else:
                    break
            weight = 0.0 if streak >= consecutive_losses else 1.0 / len(columns)
            return pd.Series(weight, index=columns, dtype="float64")

        return self._backend.run_targets(
            scenario, placeholder, target_policy=policy
        )

    def run_subscription_probe(
        self, scenario: Any, subscriptions: Mapping[str, int]
    ) -> BackendRunResult:
        self._mark_invocation()
        data = scenario.data or {}
        rows: list[dict[str, Any]] = []
        for decision_date in scenario.execution_price.index:
            for dataset, lookback in subscriptions.items():
                if dataset not in data:
                    raise KeyError(f"missing subscribed dataset: {dataset}")
                if lookback <= 0:
                    raise ValueError("subscription lookback must be positive")
                matrix = data[dataset]
                available = matrix.loc[matrix.index < decision_date].tail(lookback)
                rows.append(
                    {
                        "decision_date": pd.Timestamp(decision_date),
                        "dataset": dataset,
                        "row_count": int(len(available)),
                        "max_observation_date": (
                            pd.NaT
                            if available.empty
                            else pd.Timestamp(available.index.max())
                        ),
                    }
                )
        targets = _zero_targets(scenario)
        return self._backend.run_targets(
            scenario, targets, observation_rows=pd.DataFrame(rows)
        )

    def run_stateful_probe(self, scenario: Any) -> BackendRunResult:
        self._mark_invocation()
        rows = [
            {"decision_date": pd.Timestamp(date), "memory_counter": position + 1}
            for position, date in enumerate(scenario.execution_price.index)
        ]
        return self._backend.run_targets(
            scenario, _zero_targets(scenario), state_rows=pd.DataFrame(rows)
        )

    def run_universe_probe(
        self, scenario: Any, *, reentry_policy: str | None
    ) -> BackendRunResult:
        self._mark_invocation()
        if reentry_policy is None:
            raise ValueError("reentry memory policy must be explicit")
        if reentry_policy not in {"reset", "preserve"}:
            raise ValueError(f"unsupported reentry policy: {reentry_policy}")
        physical = scenario.execution_price.columns
        placeholder = _zero_targets(scenario)

        def policy(date: pd.Timestamp, feedback: Mapping[str, Any]) -> pd.Series:
            del feedback
            active = scenario.universe.loc[date].astype(bool)
            target = pd.Series(0.0, index=physical, dtype="float64")
            names = active.index[active].intersection(physical)
            if len(names):
                target.loc[names] = 1.0 / len(names)
            return target

        return self._backend.run_targets(
            scenario, placeholder, target_policy=policy
        )

    def run_weight_targets(
        self,
        scenario: Any,
        target_weights: pd.DataFrame,
        *,
        signals: Mapping[str, pd.DataFrame] | None = None,
    ) -> BackendRunResult:
        self._mark_invocation()
        return self._backend.run_targets(
            scenario, target_weights, signals=signals
        )

    def run_target_policy_probe(
        self,
        scenario: Any,
        target_policy: Callable[[pd.Timestamp, Mapping[str, Any]], pd.Series],
    ) -> BackendRunResult:
        placeholder = pd.DataFrame(
            0.0,
            index=scenario.execution_price.index,
            columns=scenario.execution_price.columns,
        )
        return self._backend.run_targets(
            scenario, placeholder, target_policy=target_policy
        )

    def run_cached_ensemble(
        self,
        scenario: Any,
        member_artifacts: Mapping[str, pd.DataFrame],
        *,
        etf_weight: float,
    ) -> BackendRunResult:
        self._mark_invocation()
        if not 0.0 <= etf_weight <= 1.0:
            raise ValueError("etf_weight must be in [0, 1]")
        if not member_artifacts:
            raise ValueError("member_artifacts must not be empty")
        members = list(member_artifacts.values())
        first = members[0]
        for name, member in member_artifacts.items():
            if not member.index.equals(first.index) or not member.columns.equals(
                first.columns
            ):
                raise ValueError(f"member artifact axes mismatch: {name}")
        combined = sum(member.astype("float64") for member in members) / len(members)
        physical = scenario.execution_price.columns
        research_names = scenario.universe.columns
        target = pd.DataFrame(0.0, index=first.index, columns=physical)
        etfs = [
            instrument
            for instrument in physical
            if str(scenario.asset_class.loc[instrument]) == "etf"
        ]
        if len(etfs) != 1:
            raise ValueError("cached ensemble requires exactly one physical ETF")
        target.loc[:, etfs[0]] = etf_weight
        direct_budget = 1.0 - etf_weight
        for date in target.index:
            active = scenario.universe.loc[date].astype(bool)
            names = active.index[active].intersection(research_names)
            if len(names):
                # 결합한 signed alpha는 active tilt이며 zero book은 ETF를 physical asset으로
                # 유지하면서 direct benchmark financing을 동일하게 남깁니다.
                base = pd.Series(1.0 / len(names), index=names)
                tilt = combined.loc[date, names]
                tilt = tilt - tilt.mean()
                proposed = (base + 0.1 * tilt).clip(lower=0.0)
                proposed = proposed / proposed.sum()
                target.loc[date, names] = direct_budget * proposed
        research = pd.DataFrame(
            [
                {
                    "trade_date": pd.Timestamp(date),
                    "candidate_id": "combined_alpha",
                    "score": float(row.abs().max()),
                    "selected": True,
                    "max_observation_date": pd.Timestamp(date),
                    "diagnostics": json.dumps(
                        {"member_count": len(member_artifacts)}, sort_keys=True
                    ),
                }
                for date, row in combined.iterrows()
            ]
        )
        result = self._backend.run_targets(
            scenario, target, research_rows=research
        )
        result.evidence["member_strategy_invocations"] = 0
        return result

    def run_adaptive_rules(
        self,
        scenario: Any,
        candidate_rules: tuple[str, ...],
        *,
        lookback: int,
    ) -> BackendRunResult:
        self._mark_invocation()
        if lookback <= 0 or not candidate_rules:
            raise ValueError("adaptive rules require candidates and positive lookback")
        payoff = (scenario.data or {}).get("candidate_payoff")
        if payoff is None:
            raise KeyError("missing candidate_payoff dataset")
        missing = set(candidate_rules) - set(payoff.columns)
        if missing:
            raise KeyError(f"candidate_payoff is missing rules: {sorted(missing)}")
        selected: dict[pd.Timestamp, str] = {}
        evaluations: list[dict[str, Any]] = []
        for date in scenario.execution_price.index:
            history = payoff.loc[payoff.index < date].tail(lookback)
            scores = history.loc[:, candidate_rules].mean()
            if history.empty:
                chosen = candidate_rules[0]
            else:
                chosen = max(candidate_rules, key=lambda name: (scores[name], -candidate_rules.index(name)))
            selected[pd.Timestamp(date)] = chosen
            max_date = pd.NaT if history.empty else pd.Timestamp(history.index.max())
            for candidate in candidate_rules:
                evaluations.append(
                    {
                        "trade_date": pd.Timestamp(date),
                        "candidate_id": candidate,
                        "score": (
                            float("nan") if history.empty else float(scores[candidate])
                        ),
                        "selected": candidate == chosen,
                        "max_observation_date": max_date,
                        "diagnostics": "{}",
                        "actual_orders_during_evaluation": 0,
                        "actual_cash_delta_during_evaluation": 0.0,
                        "actual_position_delta_during_evaluation": 0,
                    }
                )
        rules = pd.Series(selected, dtype="object")
        targets = _rule_targets(scenario, rules)
        return self._backend.run_targets(
            scenario,
            targets,
            selected_rules=rules,
            research_rows=pd.DataFrame(evaluations),
        )

    def run_adaptive_model(
        self,
        scenario: Any,
        *,
        train_dataset: str,
        retrain_every: int,
    ) -> BackendRunResult:
        self._mark_invocation()
        if retrain_every <= 0:
            raise ValueError("retrain_every must be positive")
        dataset = (scenario.data or {}).get(train_dataset)
        if dataset is None:
            raise KeyError(f"missing train dataset: {train_dataset}")
        required = {"feature", "realized_return"}
        if not required <= set(dataset.columns):
            raise KeyError(f"train dataset is missing columns: {sorted(required - set(dataset.columns))}")
        model_version = 0
        slope = 1.0
        training_max_date = pd.NaT
        selected: dict[pd.Timestamp, str] = {}
        states: list[dict[str, Any]] = []
        evaluations: list[dict[str, Any]] = []
        for position, date in enumerate(scenario.execution_price.index):
            retrained = position > 0 and (position - 1) % retrain_every == 0
            if retrained:
                history = dataset.loc[dataset.index < date].tail(retrain_every * 2)
                if history.empty:
                    raise ValueError("scheduled retrain has no causal training rows")
                covariance_sign = history["feature"] * history["realized_return"]
                slope = float(covariance_sign.mean())
                model_version += 1
                training_max_date = pd.Timestamp(history.index.max())
            rule = "momentum" if slope >= 0 else "reversal"
            selected[pd.Timestamp(date)] = rule
            states.append(
                {
                    "decision_date": pd.Timestamp(date),
                    "training_max_date": training_max_date,
                    "model_version": model_version,
                    "retrained": bool(retrained),
                }
            )
            evaluations.append(
                {
                    "trade_date": pd.Timestamp(date),
                    "candidate_id": f"model-v{model_version}",
                    "score": slope,
                    "selected": True,
                    "max_observation_date": training_max_date,
                    "diagnostics": json.dumps({"rule": rule}, sort_keys=True),
                }
            )
        rules = pd.Series(selected, dtype="object")
        return self._backend.run_targets(
            scenario,
            _rule_targets(scenario, rules),
            selected_rules=rules,
            research_rows=pd.DataFrame(evaluations),
            state_rows=pd.DataFrame(states),
        )

    def resume_equivalence_probe(
        self, scenario: Any, checkpoint_dir: Path
    ) -> tuple[BackendRunResult, BackendRunResult]:
        self._mark_invocation()
        dates = scenario.execution_price.index
        target = pd.DataFrame(
            0.6, index=dates, columns=scenario.execution_price.columns
        )
        signal = {
            "resume_signal": scenario.execution_price.pct_change(fill_method=None).fillna(0.0)
        }
        full = self._backend.run_targets(scenario, target, signals=signal)
        split = len(dates) // 2
        prefix = self._backend.run_targets(
            scenario, target, signals=signal, end_position=split
        )
        self._write_checkpoint(checkpoint_dir, target, signal, prefix)
        resumed = self.resume_from_checkpoint(scenario, checkpoint_dir)
        return full, resumed

    def resume_from_checkpoint(
        self, scenario: Any, checkpoint_path: Path
    ) -> BackendRunResult:
        path = Path(checkpoint_path)
        try:
            if not path.is_dir():
                raise ValueError("checkpoint path must be a checkpoint directory")
            metadata = json.loads((path / "state.json").read_text(encoding="utf-8"))
            if metadata.get("schema") != CHECKPOINT_SCHEMA:
                raise ValueError("checkpoint schema/version is invalid")
            state = ResumeState(
                next_position=int(metadata["next_position"]),
                cash=float(metadata["cash"]),
                nav=float(metadata["nav"]),
                accumulated_return=float(metadata["accumulated_return"]),
                accumulated_cost=float(metadata["accumulated_cost"]),
                accumulated_turnover=float(metadata["accumulated_turnover"]),
                adjusted_quantity={
                    str(key): float(value)
                    for key, value in metadata["adjusted_quantity"].items()
                },
                quote_price={
                    str(key): float(value)
                    for key, value in metadata["quote_price"].items()
                },
                next_order_number=int(metadata["next_order_number"]),
                next_fill_number=int(metadata["next_fill_number"]),
            )
            target = pd.read_parquet(path / "target_weights.parquet")
            target.index = pd.DatetimeIndex(target.index)
            signal_frame = pd.read_parquet(path / "signals_input.parquet")
            signal_frame.index = pd.DatetimeIndex(signal_frame.index)
            prefix = _read_result(path / "prefix")
        except (KeyError, TypeError, json.JSONDecodeError, OSError, ValueError) as exc:
            raise ValueError(f"checkpoint schema/version is invalid: {exc}") from exc
        suffix = self._backend.run_targets(
            scenario,
            target,
            signals={"resume_signal": signal_frame},
            start_position=state.next_position,
            resume_state=state,
        )
        return _merge_results(prefix, suffix)

    def artifact_store(self, root: Path) -> ParquetArtifactStore:
        return ParquetArtifactStore(root)

    def strategy_invocation_count(self) -> int:
        return self._strategy_invocations

    def optimize_portfolio(self, scenario: Any):
        problem = _optimization_problem(scenario)
        optimizer = CvxpyIntentTrackingOptimizer(
            OptimizerConfig(solver=scenario.solver)
        )
        return optimizer.optimize(problem)

    def run_optimizer_feedback_loop(
        self, scenario: Any, optimization: Any
    ) -> BackendRunResult:
        problem = _optimization_problem(optimization)
        policy = OptimizationTargetPolicy(
            CvxpyIntentTrackingOptimizer(
                OptimizerConfig(solver=optimization.solver)
            ),
            problem,
        )
        placeholder = pd.DataFrame(
            0.0,
            index=scenario.execution_price.index,
            columns=scenario.execution_price.columns,
        )
        result = self._backend.run_targets(
            scenario, placeholder, target_policy=policy
        )
        result.state_rows = pd.DataFrame(policy.audit_rows)
        return result
    def _mark_invocation(self) -> None:
        self._strategy_invocations += 1

    def _write_checkpoint(
        self,
        root: Path,
        target: pd.DataFrame,
        signals: Mapping[str, pd.DataFrame],
        prefix: BackendRunResult,
    ) -> None:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        state = prefix.evidence["resume_state"]
        if not isinstance(state, ResumeState):
            raise TypeError("backend did not return a ResumeState")
        metadata = {"schema": CHECKPOINT_SCHEMA, **asdict(state)}
        (root / "state.json").write_text(
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        target.to_parquet(root / "target_weights.parquet")
        signals["resume_signal"].to_parquet(root / "signals_input.parquet")
        _write_result(root / "prefix", prefix)


def _optimization_problem(scenario: Any) -> OptimizationProblem:
    constraints = tuple(
        LinearConstraintSpec(
            name=item.name,
            coefficients=item.coefficients,
            lower=item.lower,
            upper=item.upper,
            soft_penalty=item.soft_penalty,
            cash_coefficient=item.cash_coefficient,
        )
        for item in scenario.constraints
    )
    return OptimizationProblem(
        desired_active_exposure=scenario.desired_active_exposure,
        benchmark_weight=scenario.benchmark_weight,
        current_physical_weight=scenario.current_physical_weight,
        current_cash_weight=scenario.current_cash_weight,
        lookthrough_matrix=scenario.lookthrough_matrix,
        tradable=scenario.tradable,
        lower_bounds=scenario.lower_bounds,
        upper_bounds=scenario.upper_bounds,
        transaction_cost=scenario.transaction_cost,
        constraints=constraints,
        turnover_penalty=scenario.turnover_penalty,
        risk_penalty=scenario.risk_penalty,
        risk_covariance=scenario.risk_covariance,
        cash_lower=scenario.cash_lower,
        cash_upper=scenario.cash_upper,
    )


def build_harness() -> AcceptanceHarness:
    return AcceptanceHarness()


def _zero_targets(scenario: Any) -> pd.DataFrame:
    return pd.DataFrame(
        0.0,
        index=scenario.execution_price.index,
        columns=scenario.execution_price.columns,
    )


def _rule_targets(scenario: Any, rules: pd.Series) -> pd.DataFrame:
    columns = scenario.execution_price.columns
    target = pd.DataFrame(0.0, index=scenario.execution_price.index, columns=columns)
    first = columns[0]
    for date, rule in rules.items():
        target.loc[date, first] = 1.0 if rule == "momentum" else 0.0
    return target


def _write_result(root: Path, result: BackendRunResult) -> None:
    root.mkdir(parents=True, exist_ok=True)
    result.decision_weights.to_parquet(root / "decision_weights.parquet")
    for name, frame in (
        ("orders", result.orders()),
        ("fills", result.fills()),
        ("positions", result.positions()),
        ("account", result.account_daily().reset_index()),
        ("signals", result.signals()),
        ("observations", result.observation_audit()),
        ("research", result.research_evaluations()),
        ("feedback", result.feedback_audit()),
        ("state", result.state_audit()),
    ):
        frame.to_parquet(root / f"{name}.parquet", index=False)
    result.selected_rules.rename("selected_rule").to_frame().to_parquet(
        root / "selected_rules.parquet"
    )


def _read_result(root: Path) -> BackendRunResult:
    decision = pd.read_parquet(root / "decision_weights.parquet")
    account = pd.read_parquet(root / "account.parquet").set_index("trade_date")
    account.index = pd.DatetimeIndex(account.index, name="trade_date")
    selected_frame = pd.read_parquet(root / "selected_rules.parquet")
    selected = selected_frame["selected_rule"]
    selected.index = pd.DatetimeIndex(selected.index)
    return BackendRunResult(
        decision_weights=decision,
        order_rows=pd.read_parquet(root / "orders.parquet"),
        fill_rows=pd.read_parquet(root / "fills.parquet"),
        position_rows=pd.read_parquet(root / "positions.parquet"),
        account_rows=account,
        signal_rows=pd.read_parquet(root / "signals.parquet"),
        observation_rows=pd.read_parquet(root / "observations.parquet"),
        research_rows=pd.read_parquet(root / "research.parquet"),
        feedback_rows=pd.read_parquet(root / "feedback.parquet"),
        state_rows=pd.read_parquet(root / "state.parquet"),
        selected_rules=selected,
        evidence={"execution_backend": "qlib"},
    )


def _merge_results(
    prefix: BackendRunResult, suffix: BackendRunResult
) -> BackendRunResult:
    def rows(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
        return pd.concat([left, right], ignore_index=True)

    merged = BackendRunResult(
        decision_weights=pd.concat(
            [prefix.decision_weights, suffix.decision_weights]
        ),
        order_rows=rows(prefix.orders(), suffix.orders()),
        fill_rows=rows(prefix.fills(), suffix.fills()),
        position_rows=rows(prefix.positions(), suffix.positions()),
        account_rows=pd.concat(
            [prefix.account_daily(), suffix.account_daily()]
        ),
        signal_rows=rows(prefix.signals(), suffix.signals()),
        observation_rows=rows(
            prefix.observation_audit(), suffix.observation_audit()
        ),
        research_rows=rows(
            prefix.research_evaluations(), suffix.research_evaluations()
        ),
        feedback_rows=rows(prefix.feedback_audit(), suffix.feedback_audit()),
        state_rows=rows(prefix.state_audit(), suffix.state_audit()),
        selected_rules=pd.concat([prefix.selected_rules, suffix.selected_rules]),
        evidence=dict(suffix.evidence),
    )
    merged.evidence["execution_backend"] = "qlib"
    merged.evidence["result_hash"] = merged.result_hash()
    return merged
