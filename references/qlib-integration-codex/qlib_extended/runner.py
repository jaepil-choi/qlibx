from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

from .config import ConfigurationError, ProjectConfig, load_project_config
from .data import MatrixCatalog
from .execution import ExecutionContext, run_qlib_backtest
from .models import BatchOutcome, ComputedStrategyRun, StrategyRun
from .planning import RunPlan, alpha_record, backtest_record, build_plan, load_callable
from .store import ParentLink, RunCatalog


def run_strategy_batch(
    config_path: str | Path,
    *,
    strategy_ids: tuple[str, ...],
    max_workers: int = 1,
) -> BatchOutcome:
    project = load_project_config(config_path)
    selected = _validate_strategy_selection(project, strategy_ids)
    workers = (os.cpu_count() or 1) if max_workers == 0 else max_workers
    if workers < 1:
        raise ConfigurationError("max_workers must be non-negative")
    store = RunCatalog.initialize(project.store.catalog_uri, project.store.artifact_dir)
    plans = tuple(build_plan(project, strategy_id) for strategy_id in selected)
    pending: list[tuple[RunPlan, pd.DataFrame | None]] = []
    outcomes: dict[str, StrategyRun] = {}
    for plan in plans:
        alpha_cached = store.has_complete(plan.alpha_run_id)
        backtest_cached = store.has_complete(plan.backtest_run_id)
        if alpha_cached and backtest_cached:
            outcomes[plan.strategy_id] = _summary(plan, cached=True)
            continue
        cached_alpha = store.load_alpha(plan.alpha_run_id) if alpha_cached else None
        pending.append((plan, cached_alpha))

    if pending:
        computed = _compute_pending(project.path, pending, workers)
        for plan, cached_alpha in pending:
            result = computed[plan.strategy_id]
            if cached_alpha is None:
                store.publish(alpha_record(project, plan), {"alpha": result.alpha})
            store.publish(
                backtest_record(project, plan, result.backtest_metadata),
                result.backtest_artifacts,
                parents=(ParentLink(plan.alpha_run_id, "alpha_input"),),
            )
            outcomes[plan.strategy_id] = _summary(plan, cached=False)
    return BatchOutcome(runs=tuple(outcomes[strategy_id] for strategy_id in selected))


def _compute_pending(
    config_path: Path,
    pending: list[tuple[RunPlan, pd.DataFrame | None]],
    workers: int,
) -> dict[str, ComputedStrategyRun]:
    if workers == 1:
        return {
            plan.strategy_id: _compute_strategy(config_path, plan.strategy_id, cached)
            for plan, cached in pending
        }
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            plan.strategy_id: executor.submit(
                _compute_strategy, config_path, plan.strategy_id, cached
            )
            for plan, cached in pending
        }
        return {strategy_id: future.result() for strategy_id, future in futures.items()}


def _compute_strategy(
    config_path: Path,
    strategy_id: str,
    cached_alpha: pd.DataFrame | None,
) -> ComputedStrategyRun:
    project = load_project_config(config_path)
    data = MatrixCatalog(project)
    strategy = project.strategies[strategy_id]
    if cached_alpha is None:
        callable_object = load_callable(strategy.callable_path)
        datasets = {alias: data.load(name) for alias, name in strategy.datasets.items()}
        alpha = callable_object(datasets, **strategy.parameters)
    else:
        alpha = cached_alpha
    context = _context_from_catalog(project, data)
    backtest = run_qlib_backtest(alpha, project.backtest, context)
    return ComputedStrategyRun(
        alpha=alpha,
        backtest_artifacts=backtest.artifacts,
        backtest_metadata=backtest.metadata,
    )


def _context_from_catalog(project: ProjectConfig, data: MatrixCatalog) -> ExecutionContext:
    config = project.backtest
    matched = config.matched_capitalization
    return ExecutionContext(
        execution_price=data.load(config.execution_price),
        valuation_price=(
            None
            if config.valuation_price is None
            else data.load(config.valuation_price)
        ),
        position_unit_factor=(
            None
            if config.position_unit_factor is None
            else data.load(config.position_unit_factor)
        ),
        universe=data.load(config.universe),
        benchmark_weight=data.load(config.benchmark_weight),
        observed=None if matched is None else data.load(matched.observed),
        tradable=None if matched is None else data.load(matched.tradable),
        shortable=None if matched is None else data.load(matched.shortable),
        volume=(
            None
            if config.execution.volume is None
            else data.load(config.execution.volume)
        ),
    )


def _validate_strategy_selection(
    project: ProjectConfig, strategy_ids: tuple[str, ...]
) -> tuple[str, ...]:
    if not strategy_ids:
        raise ConfigurationError("at least one strategy_id is required")
    if len(set(strategy_ids)) != len(strategy_ids):
        raise ConfigurationError("strategy_ids must not contain duplicates")
    missing = sorted(set(strategy_ids).difference(project.strategies))
    if missing:
        raise ConfigurationError(f"unknown strategy_ids: {missing}")
    return strategy_ids


def _summary(plan: RunPlan, *, cached: bool) -> StrategyRun:
    return StrategyRun(
        strategy_id=plan.strategy_id,
        alpha_run_id=plan.alpha_run_id,
        backtest_run_id=plan.backtest_run_id,
        status="complete",
        cached=cached,
    )
