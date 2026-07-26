from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from .config import BacktestConfig
from .execution import ExecutionContext, run_qlib_backtest
from .hashing import deterministic_run_id, stable_hash
from .models import RunRecord, StrategyRun
from .store import ParentLink, RunCatalog


def build_ensemble(
    catalog_path: str | Path,
    *,
    strategy_id: str,
    members: Mapping[str, float],
) -> StrategyRun:
    store = RunCatalog.open(catalog_path)
    normalized_members = _validate_members(store, members)
    context_fingerprint, template = _common_backtest_context(store, normalized_members)
    alphas = {run_id: store.load_alpha(run_id) for run_id in normalized_members}
    ensemble_alpha = _weighted_alpha(alphas, normalized_members)
    member_definition = tuple(sorted(normalized_members.items()))
    strategy_fingerprint = stable_hash(
        {"implementation": "weighted_alpha_v1", "members": member_definition}
    )
    config_fingerprint = stable_hash(
        {"strategy_id": strategy_id, "members": member_definition}
    )
    dataset_fingerprint = stable_hash(
        {
            run_id: store.get_run(run_id).dataset_fingerprint
            for run_id in sorted(normalized_members)
        }
    )
    alpha_run_id = deterministic_run_id(
        "alpha",
        {
            "config": config_fingerprint,
            "data": dataset_fingerprint,
            "strategy": strategy_fingerprint,
        },
    )
    backtest_config = BacktestConfig(**template.metadata["backtest_config"])
    execution_fingerprint = str(template.metadata["execution_fingerprint"])
    backtest_run_id = deterministic_run_id(
        "backtest",
        {
            "alpha_run_id": alpha_run_id,
            "context": context_fingerprint,
            "execution": execution_fingerprint,
        },
    )
    if store.has_complete(alpha_run_id) and store.has_complete(backtest_run_id):
        return _summary(strategy_id, alpha_run_id, backtest_run_id, cached=True)
    if not store.has_complete(alpha_run_id):
        store.publish(
            RunRecord(
                run_id=alpha_run_id,
                run_kind="alpha",
                strategy_id=strategy_id,
                status="complete",
                config_fingerprint=config_fingerprint,
                dataset_fingerprint=dataset_fingerprint,
                strategy_fingerprint=strategy_fingerprint,
                metadata={"ensemble_method": "weighted", "members": member_definition},
            ),
            {"alpha": ensemble_alpha},
            parents=tuple(
                ParentLink(run_id, "member", weight)
                for run_id, weight in member_definition
            ),
        )
    if not store.has_complete(backtest_run_id):
        context = _load_execution_context(store, template.run_id, backtest_config)
        output = run_qlib_backtest(ensemble_alpha, backtest_config, context)
        store.publish(
            RunRecord(
                run_id=backtest_run_id,
                run_kind="backtest",
                strategy_id=strategy_id,
                status="complete",
                config_fingerprint=stable_hash(backtest_config.identity_payload()),
                dataset_fingerprint=template.dataset_fingerprint,
                strategy_fingerprint=execution_fingerprint,
                metadata={
                    "backtest_config": asdict(backtest_config),
                    "context_fingerprint": context_fingerprint,
                    "execution_fingerprint": execution_fingerprint,
                    **output.metadata,
                },
            ),
            output.artifacts,
            parents=(ParentLink(alpha_run_id, "alpha_input"),),
        )
    return _summary(strategy_id, alpha_run_id, backtest_run_id, cached=False)


def _validate_members(store: RunCatalog, members: Mapping[str, float]) -> dict[str, float]:
    if not members:
        raise ValueError("ensemble requires at least one member alpha run")
    normalized = {str(run_id): float(weight) for run_id, weight in members.items()}
    if not np.isfinite(list(normalized.values())).all() or any(
        weight < 0 for weight in normalized.values()
    ):
        raise ValueError("ensemble weights must be finite and non-negative")
    if not np.isclose(sum(normalized.values()), 1.0):
        raise ValueError("ensemble weights must sum to 1")
    for run_id in normalized:
        if store.get_run(run_id).run_kind != "alpha":
            raise ValueError(f"ensemble member is not an alpha run: {run_id}")
    return normalized


def _weighted_alpha(
    alphas: Mapping[str, pd.DataFrame], members: Mapping[str, float]
) -> pd.DataFrame:
    ordered = sorted(members)
    first = alphas[ordered[0]]
    result = first.astype("float64") * members[ordered[0]]
    for run_id in ordered[1:]:
        alpha = alphas[run_id]
        if not alpha.index.equals(first.index) or not alpha.columns.equals(first.columns):
            raise ValueError("ensemble member alpha axes must match exactly")
        result = result + alpha.astype("float64") * members[run_id]
    return result


def _common_backtest_context(
    store: RunCatalog, members: Mapping[str, float]
) -> tuple[str, RunRecord]:
    by_member: dict[str, dict[str, RunRecord]] = {}
    for run_id in members:
        records = store.find_backtests(run_id)
        if not records:
            raise ValueError(f"member alpha has no complete backtest context: {run_id}")
        by_member[run_id] = {
            str(record.metadata["context_fingerprint"]): record for record in records
        }
    common = set.intersection(*(set(rows) for rows in by_member.values()))
    if not common:
        raise ValueError("ensemble members do not share a backtest context")
    context_fingerprint = sorted(common)[0]
    first_member = sorted(members)[0]
    return context_fingerprint, by_member[first_member][context_fingerprint]


def _load_execution_context(
    store: RunCatalog,
    backtest_run_id: str,
    config: BacktestConfig,
) -> ExecutionContext:
    matched = config.matched_capitalization
    return ExecutionContext(
        execution_price=store.load_table(backtest_run_id, "execution_price"),
        valuation_price=(
            None
            if config.valuation_price is None
            else store.load_table(backtest_run_id, "valuation_price")
        ),
        position_unit_factor=(
            None
            if config.position_unit_factor is None
            else store.load_table(backtest_run_id, "position_unit_factor")
        ),
        universe=store.load_table(backtest_run_id, "universe"),
        benchmark_weight=store.load_table(backtest_run_id, "benchmark_weight"),
        observed=(
            None if matched is None else store.load_table(backtest_run_id, "observed")
        ),
        tradable=(
            None if matched is None else store.load_table(backtest_run_id, "tradable")
        ),
        shortable=(
            None if matched is None else store.load_table(backtest_run_id, "shortable")
        ),
        volume=(
            None
            if config.execution.volume is None
            else store.load_table(backtest_run_id, "volume")
        ),
    )


def _summary(
    strategy_id: str,
    alpha_run_id: str,
    backtest_run_id: str,
    *,
    cached: bool,
) -> StrategyRun:
    return StrategyRun(
        strategy_id=strategy_id,
        alpha_run_id=alpha_run_id,
        backtest_run_id=backtest_run_id,
        status="complete",
        cached=cached,
    )
