from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from qlib_extended.research.artifacts import ImmutableArtifactStore
from qlib_extended.research.config import read_yaml_mapping, require_mapping, require_string
from qlib_extended.research.costs import AsymmetricCostContract
from qlib_extended.research.evaluation import (
    WalkForwardScheme,
    evaluate_walk_forward_returns,
    rank_walk_forward_candidates,
)
from qlib_extended.research.loader import ConfigDrivenDataLoader
from qlib_extended.research.manifest import MemberWeight, MetricValue, RunSpec
from qlib_extended.research.pool import AlphaPoolCatalog


@dataclass(frozen=True)
class FamilyAllocation:
    market: float
    consensus: float
    control_only: bool


@dataclass(frozen=True)
class PhysicalTrialSpec:
    allocation: FamilyAllocation
    target_etf_sleeve: float
    alpha_multiplier: float
    financing_budget: float

    @property
    def name(self) -> str:
        return (
            f"mkt{self.allocation.market:.2f}_con{self.allocation.consensus:.2f}"
            f"__etf{self.target_etf_sleeve:.2f}__a{self.alpha_multiplier:.2f}"
            f"__fin{self.financing_budget:.2f}"
        )

    @property
    def realized_etf_sleeve(self) -> float:
        return self.target_etf_sleeve - self.financing_budget


@dataclass(frozen=True)
class PhysicalPortfolioConfig:
    path: Path
    key: str
    returns_key: str
    benchmark_weight_key: str
    market_alpha_key: str
    consensus_alpha_key: str
    etf_ticker: str
    minimum_realized_etf: float
    direct_stock_cap_floor: float
    unwind_horizon_days: int
    member_target_transform: str
    normalized_active_gross: float
    retry_generation: int
    allocations: tuple[FamilyAllocation, ...]
    etf_sleeves: tuple[float, ...]
    alpha_multipliers: tuple[float, ...]
    financing_budgets: tuple[float, ...]
    minimum_historical_annual_excess: float
    minimum_cumulative_excess: float
    config_hash: str

    @classmethod
    def from_yaml(cls, path: Path) -> PhysicalPortfolioConfig:
        payload = read_yaml_mapping(path)
        if payload.get("schema_version") != 1:
            raise ValueError("Physical portfolio schema_version must be 1.")
        inputs = require_mapping(payload.get("inputs"), "inputs")
        members = require_mapping(payload.get("members"), "members")
        physical = require_mapping(payload.get("physical"), "physical")
        search = require_mapping(payload.get("search"), "search")
        selection = require_mapping(payload.get("selection"), "selection")
        allocations = tuple(
            FamilyAllocation(
                market=float(item["market"]),
                consensus=float(item["consensus"]),
                control_only=bool(item["control_only"]),
            )
            for item in _mapping_list(
                search.get("family_allocations"), "search.family_allocations"
            )
        )
        for allocation in allocations:
            if min(allocation.market, allocation.consensus) < 0 or not np.isclose(
                allocation.market + allocation.consensus, 1.0
            ):
                raise ValueError("Each family allocation must be non-negative and sum to one.")
            if allocation.control_only != (
                allocation.market == 0.0 or allocation.consensus == 0.0
            ):
                raise ValueError("control_only must identify pure-family controls.")
        config = cls(
            path=path.resolve(),
            key=require_string(payload.get("key"), "key"),
            returns_key=require_string(inputs.get("returns"), "inputs.returns"),
            benchmark_weight_key=require_string(
                inputs.get("benchmark_weight"), "inputs.benchmark_weight"
            ),
            market_alpha_key=require_string(
                members.get("market_alpha_key"), "members.market_alpha_key"
            ),
            consensus_alpha_key=require_string(
                members.get("consensus_alpha_key"), "members.consensus_alpha_key"
            ),
            etf_ticker=require_string(physical.get("etf_ticker"), "physical.etf_ticker"),
            minimum_realized_etf=float(physical["minimum_realized_etf"]),
            direct_stock_cap_floor=float(physical["direct_stock_cap_floor"]),
            unwind_horizon_days=int(physical["unwind_horizon_days"]),
            member_target_transform=str(
                physical.get("member_target_transform", "absolute_active_weight")
            ),
            normalized_active_gross=float(
                physical.get("normalized_active_gross", 2.0)
            ),
            retry_generation=int(search.get("retry_generation", 0)),
            allocations=allocations,
            etf_sleeves=_float_tuple(search.get("etf_sleeves"), "etf_sleeves"),
            alpha_multipliers=_float_tuple(
                search.get("alpha_multipliers"), "alpha_multipliers"
            ),
            financing_budgets=_float_tuple(
                search.get("financing_budgets"), "financing_budgets"
            ),
            minimum_historical_annual_excess=float(
                selection["minimum_historical_annual_excess"]
            ),
            minimum_cumulative_excess=float(selection["minimum_cumulative_excess"]),
            config_hash=_hash_payload(payload),
        )
        if not 0.0 <= config.minimum_realized_etf < 1.0:
            raise ValueError("minimum_realized_etf must be in [0, 1).")
        if config.unwind_horizon_days < 1:
            raise ValueError("unwind_horizon_days must be positive.")
        if config.member_target_transform not in {
            "absolute_active_weight",
            "benchmark_scaled_active_weight",
        }:
            raise ValueError("Unsupported physical member_target_transform.")
        if config.normalized_active_gross <= 0.0:
            raise ValueError("normalized_active_gross must be positive.")
        if config.retry_generation < 0:
            raise ValueError("retry_generation must be non-negative.")
        return config

    def trial_specs(self) -> tuple[PhysicalTrialSpec, ...]:
        specs = [
            PhysicalTrialSpec(allocation, etf, multiplier, financing)
            for allocation in self.allocations
            for etf in self.etf_sleeves
            for multiplier in self.alpha_multipliers
            for financing in self.financing_budgets
            if etf - financing >= self.minimum_realized_etf - 1e-12
        ]
        return tuple(specs)


@dataclass(frozen=True)
class PhysicalTrialResult:
    spec: PhysicalTrialSpec
    desired_lookthrough: pd.DataFrame | None
    final_lookthrough: pd.DataFrame | None
    direct_stock_weight: pd.DataFrame | None
    etf_weight: pd.Series | None
    physical_target: pd.DataFrame | None
    daily: pd.DataFrame | None
    metrics: tuple[MetricValue, ...]


@dataclass(frozen=True)
class PhysicalSearchSummary:
    attempted: int
    complete: int
    failed: int
    active_ticker_count: int
    champion_trial: str
    champion_run_id: str
    historical_annual_excess: float
    cumulative_excess: float
    goal_met: bool
    registered_run_ids: tuple[str, ...]


def execute_physical_portfolio_search(
    *,
    config: PhysicalPortfolioConfig,
    loader: ConfigDrivenDataLoader,
    scheme: WalkForwardScheme,
    costs: AsymmetricCostContract,
    store: ImmutableArtifactStore,
    catalog: AlphaPoolCatalog,
    max_workers: int = 2,
) -> tuple[PhysicalSearchSummary, pd.DataFrame]:
    market_run = _require_unique_run(catalog, config.market_alpha_key)
    consensus_run = _require_unique_run(catalog, config.consensus_alpha_key)
    for row in (market_run, consensus_run):
        if row["research_track"] != "trusted" or row["status"] != "complete":
            raise ValueError("Physical portfolio member must be complete and trusted.")
    benchmark = loader.load_matrix(config.benchmark_weight_key).loc[
        scheme.start : scheme.end
    ]
    benchmark = benchmark.clip(lower=0.0).fillna(0.0)
    active_columns = benchmark.columns[benchmark.gt(0.0).any(axis=0)]
    if active_columns.empty:
        raise ValueError("Benchmark has no positive constituent weight in the period.")
    benchmark = benchmark.loc[:, active_columns].copy()
    benchmark = benchmark.div(benchmark.sum(axis=1).replace(0.0, np.nan), axis=0)
    if benchmark.isna().all(axis=1).any():
        raise ValueError("Benchmark has an empty row in the research period.")
    returns = loader.load_matrix(config.returns_key).loc[scheme.start : scheme.end]
    returns = returns.reindex(index=benchmark.index, columns=active_columns).copy()
    raw_member_targets = {
        "market": _load_target(catalog, str(market_run["run_id"]), returns),
        "consensus": _load_target(catalog, str(consensus_run["run_id"]), returns),
    }
    member_net_corrections = {
        name: float(target.sum(axis=1).abs().mean())
        for name, target in raw_member_targets.items()
    }
    neutral_member_targets = {
        name: project_benchmark_neutral(target, benchmark)
        for name, target in raw_member_targets.items()
    }
    if config.member_target_transform == "benchmark_scaled_active_weight":
        member_targets = {
            name: benchmark_scale_active_target(
                target,
                benchmark,
                target_gross=config.normalized_active_gross,
            )
            for name, target in neutral_member_targets.items()
        }
    else:
        member_targets = neutral_member_targets
    for name, target in member_targets.items():
        if target.sum(axis=1).abs().max() > 1e-6:
            raise ValueError(f"Cross-family member is not zero net: {name}")
    data_fingerprint = _hash_payload(
        {
            "catalog": loader.catalog.config_fingerprint,
            "market": market_run["data_fingerprint"],
            "consensus": consensus_run["data_fingerprint"],
        }
    )
    specs = config.trial_specs()
    results: list[PhysicalTrialResult] = []
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(specs)))) as pool:
        futures = {
            pool.submit(
                run_physical_trial,
                spec,
                config=config,
                member_targets=member_targets,
                benchmark=benchmark,
                returns=returns,
                scheme=scheme,
                costs=costs,
                include_frames=False,
                member_net_corrections=member_net_corrections,
            ): spec
            for spec in specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                results.append(future.result())
            except Exception as error:  # failed attempts remain auditable
                failures[spec.name] = f"{type(error).__name__}: {error}"
    results.sort(key=lambda item: item.spec.name)
    result_by_name = {item.spec.name: item for item in results}
    manifests: list[Path] = []
    run_specs: dict[str, RunSpec] = {}
    family_run_ids = {
        "market": str(market_run["run_id"]),
        "consensus": str(consensus_run["run_id"]),
    }
    attempt_offset = config.retry_generation * len(specs)
    for attempt, spec in enumerate(specs):
        result = result_by_name.get(spec.name)
        run_spec = RunSpec(
            alpha_key=f"{config.key}.trial.{spec.name}",
            family="market_consensus",
            run_kind="portfolio",
            research_track="trusted",
            order_calendar_key="cross_family_daily_physical_v1",
            rebalance_days=1,
            status="complete" if result is not None else "failed",
            config_hash=_hash_payload(
                {"portfolio_hash": config.config_hash, "trial": asdict(spec)}
            ),
            data_fingerprint=data_fingerprint,
            attempt=attempt_offset + attempt,
        )
        run_specs[spec.name] = run_spec
        member_weights = [
            MemberWeight(family_run_ids[family], float(weight))
            for family, weight in (
                ("market", spec.allocation.market),
                ("consensus", spec.allocation.consensus),
            )
            if weight > 0.0
        ]
        provenance: dict[str, Any] = {
            "portfolio_config": config.path.as_posix(),
            "cost_application": "once after cross-family physical netting",
            "resolved_config": asdict(spec),
            "retry_generation": config.retry_generation,
            "active_ticker_count": len(active_columns),
            "member_target_transform": config.member_target_transform,
            "true_forward_oos": False,
        }
        if result is None:
            provenance["failure_reason"] = failures[spec.name]
            run_dir = store.publish(run_spec, members=member_weights, provenance=provenance)
        else:
            run_dir = store.publish(
                run_spec,
                metrics=result.metrics,
                members=member_weights,
                provenance=provenance,
            )
        manifests.append(run_dir / "manifest.json")
    registered = list(catalog.register_manifests(manifests))

    if not results:
        reasons = sorted(set(failures.values()))
        raise RuntimeError(
            "All physical portfolio trials failed after registration: "
            + " | ".join(reasons[:3])
        )

    metric_rows = [
        {
            "candidate": result.spec.name,
            "segment": metric.segment,
            "metric": metric.metric,
            "value": metric.value,
        }
        for result in results
        for metric in result.metrics
    ]
    metrics_frame = pd.DataFrame(metric_rows)
    ranking = rank_walk_forward_candidates(
        metrics_frame, scheme, metric="net_excess_annual_return"
    )
    full = metrics_frame.loc[metrics_frame["segment"].eq("historical_full")]
    full_pivot = full.pivot(index="candidate", columns="metric", values="value")
    ranking = ranking.join(full_pivot, on="candidate")
    spec_map = {spec.name: spec for spec in specs}
    ranking["blended"] = ranking["candidate"].map(
        lambda name: not spec_map[name].allocation.control_only
    )
    ranking["goal_eligible"] = (
        ranking["eligible"]
        & ranking["blended"]
        & ranking["net_excess_annual_return"].ge(
            config.minimum_historical_annual_excess
        )
        & ranking["cumulative_benchmark_excess"].ge(
            config.minimum_cumulative_excess
        )
    )
    ranking = ranking.sort_values(
        ["goal_eligible", "blended", "selection_score", "candidate"],
        ascending=[False, False, False, True],
        ignore_index=True,
    )
    champion_name = str(ranking.iloc[0]["candidate"])
    champion = run_physical_trial(
        spec_map[champion_name],
        config=config,
        member_targets=member_targets,
        benchmark=benchmark,
        returns=returns,
        scheme=scheme,
        costs=costs,
        include_frames=True,
        member_net_corrections=member_net_corrections,
    )
    if any(
        frame is None
        for frame in (
            champion.daily,
            champion.desired_lookthrough,
            champion.final_lookthrough,
            champion.direct_stock_weight,
            champion.physical_target,
        )
    ):
        raise RuntimeError("Champion physical frames were not retained.")
    champion_spec = RunSpec(
        alpha_key=f"{config.key}.selection.generation_{config.retry_generation}",
        family="market_consensus",
        run_kind="portfolio",
        research_track="trusted",
        order_calendar_key="cross_family_daily_physical_v1",
        rebalance_days=1,
        status="complete",
        config_hash=_hash_payload(
            {
                "portfolio_hash": config.config_hash,
                "champion_trial": asdict(champion.spec),
            }
        ),
        data_fingerprint=data_fingerprint,
    )
    champion_dir = store.publish(
        champion_spec,
        metrics=champion.metrics,
        members=[
            MemberWeight(str(market_run["run_id"]), champion.spec.allocation.market),
            MemberWeight(
                str(consensus_run["run_id"]), champion.spec.allocation.consensus
            ),
        ],
        frames={
            "daily": champion.daily,
            "desired_lookthrough": champion.desired_lookthrough,
            "final_lookthrough": champion.final_lookthrough,
            "direct_stock_weight": champion.direct_stock_weight,
            "physical_target": champion.physical_target,
        },
        provenance={
            "portfolio_config": config.path.as_posix(),
            "cost_application": "once after cross-family physical netting",
            "selected_from_historical_trials": len(specs),
            "selected_trial": asdict(champion.spec),
            "retry_generation": config.retry_generation,
            "active_ticker_count": len(active_columns),
            "member_target_transform": config.member_target_transform,
            "source_member_mean_abs_net_correction": member_net_corrections,
            "true_forward_oos": False,
        },
    )
    catalog.register_manifest(champion_dir / "manifest.json")
    registered.append(champion_spec.run_id)
    champion_row = ranking.iloc[0]
    summary = PhysicalSearchSummary(
        attempted=len(specs),
        complete=len(results),
        failed=len(failures),
        active_ticker_count=len(active_columns),
        champion_trial=champion_name,
        champion_run_id=champion_spec.run_id,
        historical_annual_excess=float(champion_row["net_excess_annual_return"]),
        cumulative_excess=float(champion_row["cumulative_benchmark_excess"]),
        goal_met=bool(champion_row["goal_eligible"]),
        registered_run_ids=tuple(registered),
    )
    return summary, ranking


def run_physical_trial(
    spec: PhysicalTrialSpec,
    *,
    config: PhysicalPortfolioConfig,
    member_targets: Mapping[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    returns: pd.DataFrame,
    scheme: WalkForwardScheme,
    costs: AsymmetricCostContract,
    include_frames: bool = True,
    member_net_corrections: Mapping[str, float] | None = None,
) -> PhysicalTrialResult:
    alpha = (
        spec.allocation.market * member_targets["market"]
        + spec.allocation.consensus * member_targets["consensus"]
    )
    desired = benchmark + spec.alpha_multiplier * alpha
    etf_value = spec.realized_etf_sleeve
    lower = benchmark * etf_value
    direct_cap = benchmark.clip(lower=config.direct_stock_cap_floor).where(
        benchmark.gt(0.0), 0.0
    )
    direct = project_direct_stock(
        desired - lower,
        mass=1.0 - etf_value,
        cap=direct_cap,
        fallback=benchmark,
    )
    lookthrough = direct + lower
    etf = pd.Series(etf_value, index=benchmark.index, name=config.etf_ticker)
    physical = direct.copy()
    physical[config.etf_ticker] = etf
    if not np.allclose(physical.sum(axis=1), 1.0, atol=1e-8):
        raise RuntimeError("Physical target is not fully invested.")
    daily = simulate_physical_portfolio(
        direct,
        etf,
        benchmark,
        returns,
        financed_inventory=pd.Series(spec.financing_budget, index=benchmark.index),
        unwind_horizon_days=config.unwind_horizon_days,
        costs=costs,
    )
    tracking_rmse = desired.sub(lookthrough).pow(2).mean(axis=1).pow(0.5)
    metrics = [
        *evaluate_walk_forward_returns(
            daily["gross_excess_return"], scheme, metric_prefix="gross_excess"
        ),
        *evaluate_walk_forward_returns(
            daily["net_excess_return"], scheme, metric_prefix="net_excess"
        ),
        MetricValue(
            "historical_full",
            "annualized_trade_cost",
            float(daily["total_trade_cost"].mean() * 252),
        ),
        MetricValue(
            "historical_full", "mean_realized_etf", float(etf.mean())
        ),
        MetricValue(
            "historical_full",
            "mean_financed_inventory",
            float(spec.financing_budget),
        ),
        MetricValue(
            "historical_full", "mean_tracking_rmse", float(tracking_rmse.mean())
        ),
        MetricValue(
            "historical_full",
            "cumulative_benchmark_excess",
            _relative_cumulative_excess(
                daily["net_portfolio_return"], daily["benchmark_return"]
            ),
        ),
        MetricValue(
            "historical_full",
            "geometric_annual_excess",
            _geometric_annual_excess(
                daily["net_portfolio_return"], daily["benchmark_return"]
            ),
        ),
    ]
    for family, value in sorted((member_net_corrections or {}).items()):
        metrics.append(
            MetricValue(
                "historical_full", f"mean_abs_{family}_net_correction", float(value)
            )
        )
    return PhysicalTrialResult(
        spec=spec,
        desired_lookthrough=desired if include_frames else None,
        final_lookthrough=lookthrough if include_frames else None,
        direct_stock_weight=direct if include_frames else None,
        etf_weight=etf if include_frames else None,
        physical_target=physical if include_frames else None,
        daily=daily if include_frames else None,
        metrics=tuple(metrics),
    )


def project_direct_stock(
    desired_direct: pd.DataFrame,
    *,
    mass: float,
    cap: pd.DataFrame,
    fallback: pd.DataFrame,
) -> pd.DataFrame:
    if not 0.0 < mass <= 1.0:
        raise ValueError("Direct stock mass must be in (0, 1].")
    raw = desired_direct.clip(lower=0.0)
    raw = raw.where(raw.sum(axis=1).gt(0.0), fallback)
    projected = raw.div(raw.sum(axis=1), axis=0).mul(mass).clip(upper=cap)
    for _ in range(12):
        remaining = mass - projected.sum(axis=1)
        if float(remaining.abs().max()) <= 1e-10:
            break
        headroom = (cap - projected).clip(lower=0.0)
        score = raw.where(headroom.gt(1e-14), 0.0)
        score = score.where(score.sum(axis=1).gt(0.0), headroom)
        addition = score.div(score.sum(axis=1).replace(0.0, np.nan), axis=0).mul(
            remaining.clip(lower=0.0), axis=0
        )
        projected = (projected + addition.fillna(0.0)).clip(upper=cap)
    if (mass - projected.sum(axis=1)).abs().max() > 1e-8:
        raise RuntimeError("Direct stock projection did not converge.")
    return projected


def project_benchmark_neutral(
    active_target: pd.DataFrame,
    benchmark: pd.DataFrame,
) -> pd.DataFrame:
    if not active_target.index.equals(benchmark.index) or not active_target.columns.equals(
        benchmark.columns
    ):
        raise ValueError("Active target and benchmark axes must match.")
    benchmark_sum = benchmark.sum(axis=1)
    if not np.allclose(benchmark_sum, 1.0, atol=1e-8):
        raise ValueError("Benchmark rows must sum to one before neutral projection.")
    net = active_target.sum(axis=1)
    projected = active_target - benchmark.mul(net, axis=0)
    if projected.sum(axis=1).abs().max() > 1e-8:
        raise RuntimeError("Benchmark neutral projection failed.")
    return projected


def benchmark_scale_active_target(
    active_target: pd.DataFrame,
    benchmark: pd.DataFrame,
    *,
    target_gross: float = 2.0,
) -> pd.DataFrame:
    if target_gross <= 0.0:
        raise ValueError("target_gross must be positive.")
    if not active_target.index.equals(benchmark.index) or not active_target.columns.equals(
        benchmark.columns
    ):
        raise ValueError("Active target and benchmark axes must match.")
    weighted_mean = (active_target * benchmark).sum(axis=1)
    proportional = benchmark * active_target.sub(weighted_mean, axis=0)
    gross = proportional.abs().sum(axis=1)
    scaled = proportional.div(gross.replace(0.0, np.nan), axis=0).mul(target_gross)
    scaled = scaled.fillna(0.0)
    if scaled.sum(axis=1).abs().max() > 1e-8:
        raise RuntimeError("Benchmark-scaled active target is not zero net.")
    active_rows = gross.gt(0.0)
    if active_rows.any() and not np.allclose(
        scaled.loc[active_rows].abs().sum(axis=1), target_gross, atol=1e-8
    ):
        raise RuntimeError("Benchmark-scaled active target gross normalization failed.")
    return scaled


def simulate_physical_portfolio(
    direct: pd.DataFrame,
    etf: pd.Series,
    benchmark: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    financed_inventory: pd.Series,
    unwind_horizon_days: int,
    costs: AsymmetricCostContract,
) -> pd.DataFrame:
    etf_return = (benchmark * returns.fillna(0.0)).sum(axis=1)
    pretrade_stock_rows: list[np.ndarray] = []
    pretrade_etf: list[float] = []
    pretrade = np.zeros(direct.shape[1] + 1, dtype="float64")
    instrument_returns = pd.concat(
        [returns.fillna(0.0), etf_return.rename(etf.name)], axis=1
    )
    physical = direct.copy()
    physical[etf.name] = etf
    gross_portfolio: list[float] = []
    for date in physical.index:
        pretrade_stock_rows.append(pretrade[:-1].copy())
        pretrade_etf.append(float(pretrade[-1]))
        held = physical.loc[date].to_numpy(dtype="float64")
        realized = instrument_returns.loc[date].to_numpy(dtype="float64")
        gross = float(held @ realized)
        gross_portfolio.append(gross)
        pretrade = held * (1.0 + realized) / (1.0 + gross)
    pretrade_stock = pd.DataFrame(
        pretrade_stock_rows, index=direct.index, columns=direct.columns
    )
    pretrade_etf_series = pd.Series(pretrade_etf, index=direct.index)
    breakdown = costs.evaluate_netted_orders(
        stock_target=direct,
        stock_pretrade=pretrade_stock,
        etf_target=etf,
        etf_pretrade=pretrade_etf_series,
    )
    unwind = costs.expected_inventory_unwind_cost(
        financed_inventory, unwind_horizon_days=unwind_horizon_days
    )
    total_cost = breakdown["total_trade_cost"] + unwind
    gross_series = pd.Series(gross_portfolio, index=direct.index)
    benchmark_return = etf_return
    net_portfolio = gross_series - total_cost
    return pd.DataFrame(
        {
            "benchmark_return": benchmark_return,
            "gross_portfolio_return": gross_series,
            "net_portfolio_return": net_portfolio,
            "gross_excess_return": gross_series - benchmark_return,
            "net_excess_return": net_portfolio - benchmark_return,
            "stock_trade_cost": breakdown["stock_trade_cost"],
            "etf_trade_cost": breakdown["etf_trade_cost"],
            "expected_unwind_cost": unwind,
            "total_trade_cost": total_cost,
            "stock_buy_turnover": breakdown["stock_buy_turnover"],
            "stock_sell_turnover": breakdown["stock_sell_turnover"],
            "etf_buy_turnover": breakdown["etf_buy_turnover"],
            "etf_sell_turnover": breakdown["etf_sell_turnover"],
        },
        index=direct.index,
    )


def _relative_cumulative_excess(
    portfolio_return: pd.Series, benchmark_return: pd.Series
) -> float:
    portfolio_wealth = float((1.0 + portfolio_return).prod())
    benchmark_wealth = float((1.0 + benchmark_return).prod())
    return portfolio_wealth / benchmark_wealth - 1.0


def _geometric_annual_excess(
    portfolio_return: pd.Series, benchmark_return: pd.Series
) -> float:
    relative = 1.0 + _relative_cumulative_excess(portfolio_return, benchmark_return)
    return float(relative ** (252.0 / len(portfolio_return)) - 1.0)


def _require_unique_run(catalog: AlphaPoolCatalog, alpha_key: str) -> pd.Series:
    rows = catalog.runs()
    selected = rows.loc[rows["alpha_key"].eq(alpha_key)]
    if len(selected) != 1:
        raise ValueError(f"Expected one run for alpha_key {alpha_key}: {len(selected)}")
    return selected.iloc[0]


def _load_target(
    catalog: AlphaPoolCatalog, run_id: str, like: pd.DataFrame
) -> pd.DataFrame:
    row = catalog.runs().set_index("run_id").loc[run_id]
    path = (
        catalog.path.parent
        / Path(str(row["artifact_dir"]))
        / "target_weights.parquet"
    ).resolve()
    target = pd.read_parquet(path, columns=like.columns.tolist())
    if not target.columns.equals(like.columns):
        raise ValueError(f"Target artifact columns do not match active benchmark: {path}")
    return target.reindex(index=like.index).fillna(0.0)


def _mapping_list(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of mappings.")
    return value


def _float_tuple(value: object, label: str) -> tuple[float, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"search.{label} must be a non-empty list.")
    values = tuple(float(item) for item in value)
    if min(values) < 0.0:
        raise ValueError(f"search.{label} must be non-negative.")
    return values


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
