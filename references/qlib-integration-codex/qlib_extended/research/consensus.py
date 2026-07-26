from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from qlib_extended.research.alpha import AlphaDefinition
from qlib_extended.research.artifacts import ImmutableArtifactStore
from qlib_extended.research.costs import AsymmetricCostContract
from qlib_extended.research.evaluation import (
    WalkForwardScheme,
    evaluate_walk_forward_returns,
    rank_walk_forward_candidates,
)
from qlib_extended.research.loader import ConfigDrivenDataLoader
from qlib_extended.research.manifest import MetricValue, RunSpec
from qlib_extended.research.pool import AlphaPoolCatalog


@dataclass(frozen=True)
class ConsensusHybridInputs:
    returns: pd.DataFrame
    transaction_amount: pd.DataFrame
    universe: pd.DataFrame
    industry: pd.DataFrame
    consensus: dict[str, pd.DataFrame]
    data_fingerprint: str


@dataclass(frozen=True)
class ConsensusHybridSpec:
    name: str
    source: str
    hybrid: str
    holding_days: int
    market_weight: float = 0.5


@dataclass(frozen=True)
class ConsensusHybridTrial:
    spec: ConsensusHybridSpec
    target_weights: pd.DataFrame
    gross_returns: pd.Series
    diagnostic_net_returns: pd.Series
    metrics: tuple[MetricValue, ...]
    annualized_turnover: float


@dataclass(frozen=True)
class ConsensusHybridSummary:
    attempted: int
    complete: int
    failed: int
    selected_names: tuple[str, ...]
    selected_run_ids: tuple[str, ...]
    registered_run_ids: tuple[str, ...]


def load_consensus_hybrid_inputs(
    loader: ConfigDrivenDataLoader,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> ConsensusHybridInputs:
    market = loader.load_table("market_panel")
    market = market.loc[market["date"].between(start, end)].copy()
    _require_unique_panel(market, "market_panel")
    calendar = pd.DatetimeIndex(sorted(market["date"].unique()), name="date")
    tickers = pd.Index(sorted(market["ticker"].unique()), name="ticker")
    returns = _pivot(market, "return", calendar, tickers).astype("float64")
    transaction_amount = _pivot(market, "tx_amount", calendar, tickers).astype(
        "float64"
    )
    membership = _pivot(market, "is_k200_member", calendar, tickers).fillna(False)
    halt = _pivot(market, "is_trading_halt", calendar, tickers).fillna(True)
    admin = _pivot(market, "is_admin_issue", calendar, tickers).fillna(True)
    market_cap = _pivot(market, "market_cap", calendar, tickers)
    universe = (
        membership.astype(bool)
        & ~halt.astype(bool)
        & ~admin.astype(bool)
        & returns.notna()
        & transaction_amount.gt(0.0)
        & market_cap.gt(0.0)
    )
    industry = loader.load_matrix("industry_code", like=returns).ffill()
    industry = ((industry // 100) * 100).where(universe)

    table = loader.load_table("consensus_k200_valuation")
    table = table.loc[table["date"].between(start, end)].copy()
    _require_unique_panel(table, "consensus_k200_valuation")
    consensus = {
        field: _pivot(table, field, calendar, tickers)
        .where(lambda values: values.ne(0.0))
        .astype("float64")
        for field in ("forward_eps", "net_income_fy1")
    }
    fingerprint = _input_fingerprint(
        loader,
        source_names=(
            "adjusted_prices",
            "k200_members",
            "sector_classification",
            "fng_valuation",
        ),
        start=start,
        end=end,
    )
    return ConsensusHybridInputs(
        returns=returns,
        transaction_amount=transaction_amount,
        universe=universe,
        industry=industry,
        consensus=consensus,
        data_fingerprint=fingerprint,
    )


def build_consensus_hybrid_specs(definition: AlphaDefinition) -> tuple[ConsensusHybridSpec, ...]:
    search = definition.search
    sources = _require_string_sequence(search.get("consensus_sources"), "sources")
    hybrids = _require_string_sequence(search.get("hybrids"), "hybrids")
    holding_days = _require_int_sequence(search.get("holding_days"), "holding_days")
    market_weights = search.get("market_weight")
    if not isinstance(market_weights, list) or not market_weights:
        raise ValueError("search.market_weight must be a non-empty list.")
    specs: list[ConsensusHybridSpec] = []
    for source in sources:
        for hybrid in hybrids:
            for holding in holding_days:
                for weight in market_weights:
                    value = float(weight)
                    name = f"{source}__{hybrid}__h{holding}__mw{value:.2f}"
                    specs.append(
                        ConsensusHybridSpec(name, source, hybrid, holding, value)
                    )
    return tuple(specs)


def prepare_consensus_hybrid_scores(
    inputs: ConsensusHybridInputs,
) -> tuple[
    dict[str, pd.DataFrame],
    dict[str, pd.DataFrame],
    dict[str, pd.DataFrame],
]:
    eps = inputs.consensus["forward_eps"]
    fy1 = inputs.consensus["net_income_fy1"]
    raw_sources = {
        "eps_revision_20d": _symmetric_change(eps, 20),
        "fy1_confirmation_10d_40d": (
            _industry_rank(_symmetric_change(fy1, 10), inputs.industry, inputs.universe)
            + _industry_rank(
                _symmetric_change(fy1, 40), inputs.industry, inputs.universe
            )
        )
        / 2.0,
    }
    event_masks = {
        "eps_revision_20d": _change_event(eps) & inputs.universe,
        "fy1_confirmation_10d_40d": _change_event(fy1) & inputs.universe,
    }
    returns = inputs.returns.fillna(0.0)
    market_raw = {
        "momentum_5d": _compound_return(returns, 5).shift(1),
        "momentum_21d": _compound_return(returns, 21).shift(1),
        "abnormal_volume": (
            inputs.transaction_amount.rolling(5, min_periods=5).mean()
            / inputs.transaction_amount.rolling(63, min_periods=63).mean()
            - 1.0
        ).shift(1),
    }
    market_scores = {
        name: _industry_rank(values, inputs.industry, inputs.universe)
        for name, values in market_raw.items()
    }
    source_scores = {
        name: _industry_rank(values, inputs.industry, inputs.universe)
        for name, values in raw_sources.items()
    }
    return source_scores, event_masks, market_scores


def run_consensus_hybrid_trial(
    spec: ConsensusHybridSpec,
    *,
    inputs: ConsensusHybridInputs,
    source_scores: Mapping[str, pd.DataFrame],
    event_masks: Mapping[str, pd.DataFrame],
    market_scores: Mapping[str, pd.DataFrame],
    scheme: WalkForwardScheme,
    costs: AsymmetricCostContract,
) -> ConsensusHybridTrial:
    base = source_scores[spec.source]
    score = _combine_hybrid(base, market_scores, spec)
    event = event_masks[spec.source]
    held = _hold_event_scores(
        score.where(event),
        event,
        inputs.universe,
        spec.holding_days,
    )
    decision = _industry_neutral_scale(held, inputs.industry, inputs.universe)
    applied = decision.shift(1).fillna(0.0).where(inputs.universe, 0.0)
    applied = _industry_neutral_scale(applied, inputs.industry, inputs.universe)
    gross = (applied * inputs.returns.fillna(0.0)).sum(axis=1)
    delta = applied.diff().fillna(applied)
    buy = delta.clip(lower=0.0).sum(axis=1)
    sell = -delta.clip(upper=0.0).sum(axis=1)
    diagnostic_cost = buy * costs.stock_buy_rate + sell * costs.stock_sell_rate
    diagnostic_net = gross - diagnostic_cost
    metrics = [
        *evaluate_walk_forward_returns(
            gross, scheme, metric_prefix="gross_excess"
        ),
        *evaluate_walk_forward_returns(
            diagnostic_net, scheme, metric_prefix="diagnostic_net_excess"
        ),
        MetricValue(
            "historical_full",
            "annualized_turnover",
            float((buy + sell).mean() * 252),
        ),
        MetricValue(
            "historical_full",
            "annualized_diagnostic_cost",
            float(diagnostic_cost.mean() * 252),
        ),
    ]
    return ConsensusHybridTrial(
        spec=spec,
        target_weights=applied,
        gross_returns=gross,
        diagnostic_net_returns=diagnostic_net,
        metrics=tuple(metrics),
        annualized_turnover=float((buy + sell).mean() * 252),
    )


def execute_consensus_hybrid_search(
    *,
    definition: AlphaDefinition,
    inputs: ConsensusHybridInputs,
    scheme: WalkForwardScheme,
    costs: AsymmetricCostContract,
    store: ImmutableArtifactStore,
    catalog: AlphaPoolCatalog,
    max_workers: int = 4,
) -> tuple[ConsensusHybridSummary, pd.DataFrame]:
    if definition.family != "consensus" or definition.track != "trusted":
        raise ValueError("Consensus hybrid search requires a trusted consensus definition.")
    specs = build_consensus_hybrid_specs(definition)
    source_scores, event_masks, market_scores = prepare_consensus_hybrid_scores(inputs)
    completed: list[ConsensusHybridTrial] = []
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(specs)))) as pool:
        futures = {
            pool.submit(
                run_consensus_hybrid_trial,
                spec,
                inputs=inputs,
                source_scores=source_scores,
                event_masks=event_masks,
                market_scores=market_scores,
                scheme=scheme,
                costs=costs,
            ): spec
            for spec in specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                completed.append(future.result())
            except Exception as error:  # every attempt must be materialized
                failures[spec.name] = f"{type(error).__name__}: {error}"
    completed.sort(key=lambda trial: trial.spec.name)

    manifest_paths: list[Path] = []
    run_specs: dict[str, RunSpec] = {}
    daily_returns: dict[str, pd.Series] = {}
    for attempt, spec in enumerate(specs):
        trial = next((item for item in completed if item.spec == spec), None)
        status = "complete" if trial is not None else "failed"
        run_spec = RunSpec(
            alpha_key=f"{definition.key}.{spec.name}",
            family="consensus",
            run_kind="atomic",
            research_track="trusted",
            order_calendar_key=definition.order_calendar_key,
            rebalance_days=spec.holding_days,
            status=status,
            config_hash=_hash_payload(
                {"definition_hash": definition.config_hash, "trial": asdict(spec)}
            ),
            data_fingerprint=inputs.data_fingerprint,
            attempt=attempt,
        )
        run_specs[spec.name] = run_spec
        if trial is None:
            run_dir = store.publish(
                run_spec,
                provenance={
                    "alpha_definition": definition.path.as_posix(),
                    "failure_reason": failures[spec.name],
                    "resolved_config": asdict(spec),
                },
            )
        else:
            daily_returns[spec.name] = trial.diagnostic_net_returns
            frame = pd.DataFrame(
                {
                    "gross_excess_return": trial.gross_returns,
                    "diagnostic_net_excess_return": trial.diagnostic_net_returns,
                }
            )
            run_dir = store.publish(
                run_spec,
                metrics=trial.metrics,
                frames={
                    "daily_returns": frame,
                    "target_weights": trial.target_weights,
                },
                provenance={
                    "alpha_definition": definition.path.as_posix(),
                    "atomic_cost_classification": (
                        "selection diagnostic only; final portfolio cost must be "
                        "computed once after family and cross-family netting"
                    ),
                    "market_information_cutoff": "previous trading day",
                    "resolved_config": asdict(spec),
                    "true_forward_oos": False,
                },
            )
        manifest_paths.append(run_dir / "manifest.json")
    registered = tuple(catalog.register_manifests(manifest_paths))

    metric_rows = [
        {
            "candidate": trial.spec.name,
            "segment": metric.segment,
            "metric": metric.metric,
            "value": metric.value,
        }
        for trial in completed
        for metric in trial.metrics
    ]
    ranking = rank_walk_forward_candidates(
        pd.DataFrame(metric_rows),
        scheme,
        metric="diagnostic_net_excess_annual_return",
    )
    ranking["annualized_turnover"] = ranking["candidate"].map(
        {trial.spec.name: trial.annualized_turnover for trial in completed}
    )
    selected = _select_diversified(ranking, daily_returns, run_specs, limit=4)
    summary = ConsensusHybridSummary(
        attempted=len(specs),
        complete=len(completed),
        failed=len(failures),
        selected_names=tuple(selected),
        selected_run_ids=tuple(run_specs[name].run_id for name in selected),
        registered_run_ids=registered,
    )
    return summary, ranking


def _combine_hybrid(
    base: pd.DataFrame,
    market_scores: Mapping[str, pd.DataFrame],
    spec: ConsensusHybridSpec,
) -> pd.DataFrame:
    weight = spec.market_weight
    if spec.hybrid == "revision_only":
        return base
    if spec.hybrid == "underreaction_21d":
        return base - weight * market_scores["momentum_21d"]
    if spec.hybrid == "price_confirmation_21d":
        return base + weight * market_scores["momentum_21d"]
    if spec.hybrid == "short_drift_confirmation_5d":
        return base + weight * market_scores["momentum_5d"]
    if spec.hybrid == "abnormal_volume_confirmation":
        multiplier = 1.0 + 2.0 * weight * market_scores["abnormal_volume"]
        return base * multiplier.clip(lower=0.25, upper=1.75)
    raise ValueError(f"Unknown consensus hybrid: {spec.hybrid}")


def _hold_event_scores(
    score: pd.DataFrame,
    event: pd.DataFrame,
    universe: pd.DataFrame,
    holding_days: int,
) -> pd.DataFrame:
    values = score.to_numpy(dtype="float64")
    events = event.to_numpy(dtype=bool)
    active = universe.to_numpy(dtype=bool)
    output = np.full(values.shape, np.nan, dtype="float64")
    state = np.full(values.shape[1], np.nan, dtype="float64")
    age = np.full(values.shape[1], holding_days, dtype="int64")
    for row in range(len(score)):
        age += 1
        state[~active[row]] = np.nan
        age[~active[row]] = holding_days
        update = events[row] & active[row] & np.isfinite(values[row])
        state[update] = values[row, update]
        age[update] = 0
        expired = age >= holding_days
        state[expired] = np.nan
        output[row] = state
    return pd.DataFrame(output, index=score.index, columns=score.columns)


def _industry_rank(
    values: pd.DataFrame,
    industry: pd.DataFrame,
    universe: pd.DataFrame,
) -> pd.DataFrame:
    stacked = values.where(universe & industry.notna()).stack().rename("value").to_frame()
    groups = industry.where(universe).stack().rename("industry")
    table = stacked.join(groups, how="inner")
    keys = [table.index.get_level_values(0), table["industry"]]
    count = table.groupby(keys, sort=False)["value"].transform("count")
    rank = table.groupby(keys, sort=False)["value"].rank(pct=True, method="average")
    centered = rank - rank.groupby(keys, sort=False).transform("mean")
    centered = centered.where(count.ge(3))
    return centered.unstack().reindex(index=values.index, columns=values.columns)


def _industry_neutral_scale(
    values: pd.DataFrame,
    industry: pd.DataFrame,
    universe: pd.DataFrame,
) -> pd.DataFrame:
    stacked = values.where(universe & industry.notna()).stack().rename("value").to_frame()
    groups = industry.where(universe).stack().rename("industry")
    table = stacked.join(groups, how="inner")
    if table.empty:
        return pd.DataFrame(0.0, index=values.index, columns=values.columns)
    keys = [table.index.get_level_values(0), table["industry"]]
    count = table.groupby(keys, sort=False)["value"].transform("count")
    table["value"] -= table.groupby(keys, sort=False)["value"].transform("mean")
    table["value"] = table["value"].where(count.ge(3), 0.0)
    wide = table["value"].unstack().reindex(
        index=values.index, columns=values.columns
    ).fillna(0.0)
    gross = wide.abs().sum(axis=1).replace(0.0, np.nan)
    return wide.div(gross, axis=0).mul(2.0).fillna(0.0)


def _select_diversified(
    ranking: pd.DataFrame,
    daily_returns: Mapping[str, pd.Series],
    run_specs: Mapping[str, RunSpec],
    *,
    limit: int,
) -> list[str]:
    del run_specs
    selected: list[str] = []
    for candidate in ranking.loc[ranking["eligible"], "candidate"]:
        if any(
            abs(float(daily_returns[candidate].corr(daily_returns[member]))) >= 0.80
            for member in selected
        ):
            continue
        selected.append(str(candidate))
        if len(selected) == limit:
            break
    return selected


def _symmetric_change(values: pd.DataFrame, lookback: int) -> pd.DataFrame:
    previous = values.shift(lookback)
    denominator = values.abs() + previous.abs()
    return (2.0 * (values - previous) / denominator.where(denominator.gt(0.0))).replace(
        [np.inf, -np.inf], np.nan
    )


def _change_event(values: pd.DataFrame) -> pd.DataFrame:
    previous = values.shift(1)
    return values.ne(previous) & values.notna() & previous.notna()


def _compound_return(returns: pd.DataFrame, window: int) -> pd.DataFrame:
    return (1.0 + returns).rolling(window, min_periods=window).apply(
        np.prod, raw=True
    ) - 1.0


def _pivot(
    table: pd.DataFrame,
    value: str,
    calendar: pd.DatetimeIndex,
    tickers: pd.Index,
) -> pd.DataFrame:
    return table.pivot(index="date", columns="ticker", values=value).reindex(
        index=calendar, columns=tickers
    )


def _require_unique_panel(table: pd.DataFrame, name: str) -> None:
    missing = sorted({"date", "ticker"} - set(table.columns))
    if missing:
        raise KeyError(f"{name} is missing columns: {missing}")
    if table.duplicated(["date", "ticker"]).any():
        raise ValueError(f"{name} has duplicate date/ticker rows.")


def _require_string_sequence(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or any(not isinstance(x, str) for x in value):
        raise ValueError(f"search.{name} must be a non-empty string list.")
    return tuple(value)


def _require_int_sequence(value: object, name: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value or any(
        not isinstance(x, int) or isinstance(x, bool) or x < 1 or x > 63 for x in value
    ):
        raise ValueError(f"search.{name} must contain integers in [1, 63].")
    return tuple(value)


def _input_fingerprint(
    loader: ConfigDrivenDataLoader,
    *,
    source_names: tuple[str, ...],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> str:
    sources: dict[str, dict[str, Any]] = {}
    for name in source_names:
        path = loader.catalog.require_source(name).path
        stat = path.stat()
        sources[name] = {
            "path": path.as_posix(),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    return _hash_payload(
        {
            "catalog": loader.catalog.config_fingerprint,
            "sources": sources,
            "start": str(start.date()),
            "end": str(end.date()),
        }
    )


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
