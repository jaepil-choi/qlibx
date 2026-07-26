from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import pandas as pd

from qlib_extended.research.alpha import AlphaDefinition
from qlib_extended.research.artifacts import ImmutableArtifactStore
from qlib_extended.research.costs import AsymmetricCostContract, cross_member_targets
from qlib_extended.research.evaluation import (
    WalkForwardScheme,
    evaluate_walk_forward_returns,
    rank_walk_forward_candidates,
)
from qlib_extended.research.loader import ConfigDrivenDataLoader
from qlib_extended.research.manifest import MemberWeight, MetricValue, RunSpec
from qlib_extended.research.pool import AlphaPoolCatalog


@dataclass(frozen=True)
class ConsensusCohortSummary:
    attempted: int
    selected_name: str
    selected_run_id: str
    registered_run_ids: tuple[str, ...]


def publish_consensus_calendar_cohorts(
    selection_summary_path: Path,
    *,
    definition: AlphaDefinition,
    loader: ConfigDrivenDataLoader,
    scheme: WalkForwardScheme,
    costs: AsymmetricCostContract,
    store: ImmutableArtifactStore,
    catalog: AlphaPoolCatalog,
) -> tuple[ConsensusCohortSummary, pd.DataFrame]:
    selection = json.loads(selection_summary_path.read_text(encoding="utf-8"))
    run_ids = [str(value) for value in selection["selected_run_ids"]]
    names = [str(value) for value in selection["selected_names"]]
    if len(run_ids) != len(names) or len(run_ids) < 2:
        raise ValueError("Consensus selection must contain matching names and run IDs.")
    runs = catalog.runs().set_index("run_id")
    selected_runs = runs.loc[run_ids]
    if set(selected_runs["family"]) != {"consensus"}:
        raise ValueError("Consensus cohort contains a non-consensus member.")
    if set(selected_runs["research_track"]) != {"trusted"}:
        raise ValueError("Consensus cohort contains an untrusted member.")
    calendars = set(selected_runs["order_calendar_key"])
    if len(calendars) != 1:
        raise ValueError(f"Consensus members do not share one calendar: {calendars}")
    data_fingerprints = set(selected_runs["data_fingerprint"])
    if len(data_fingerprints) != 1:
        raise ValueError("Consensus members do not share one data fingerprint.")

    targets = {
        name: _load_artifact_frame(catalog, run_id, "target_weights")
        for name, run_id in zip(names, run_ids, strict=True)
    }
    turnovers = _member_turnovers(catalog, run_ids, names)
    schemes = _consensus_weight_schemes(names, turnovers)
    returns = loader.load_matrix("adjusted_return")
    returns = returns.loc[scheme.start : scheme.end]
    manifests: list[Path] = []
    specs: dict[str, RunSpec] = {}
    metric_rows: list[dict[str, object]] = []

    for attempt, (scheme_name, weights) in enumerate(schemes.items()):
        target = cross_member_targets(targets, weights).reindex(
            index=returns.index, columns=returns.columns
        ).fillna(0.0)
        gross, net, extra = _evaluate_crossed_target(target, returns, costs)
        metrics = [
            *evaluate_walk_forward_returns(
                gross, scheme, metric_prefix="gross_excess"
            ),
            *evaluate_walk_forward_returns(net, scheme, metric_prefix="net_excess"),
            *extra,
        ]
        spec = RunSpec(
            alpha_key=f"{definition.key}.calendar_cohort.{scheme_name}",
            family="consensus",
            run_kind="cohort",
            research_track="trusted",
            order_calendar_key=next(iter(calendars)),
            rebalance_days=int(selected_runs["rebalance_days"].max()),
            status="complete",
            config_hash=_hash_payload(
                {
                    "definition_hash": definition.config_hash,
                    "scheme": scheme_name,
                    "weights": weights,
                }
            ),
            data_fingerprint=next(iter(data_fingerprints)),
            attempt=attempt,
        )
        specs[scheme_name] = spec
        run_dir = store.publish(
            spec,
            metrics=metrics,
            members=[
                MemberWeight(run_id, float(weights[name]))
                for name, run_id in zip(names, run_ids, strict=True)
                if weights[name] != 0.0
            ],
            frames={
                "daily_returns": pd.DataFrame(
                    {"gross_excess_return": gross, "net_excess_return": net}
                ),
                "target_weights": target,
            },
            provenance={
                "alpha_definition": definition.path.as_posix(),
                "cost_application": "once after same-calendar member crossing",
                "member_weight_scheme": scheme_name,
                "resolved_member_weights": weights,
                "true_forward_oos": False,
            },
        )
        manifests.append(run_dir / "manifest.json")
        metric_rows.extend(
            {
                "candidate": scheme_name,
                "segment": metric.segment,
                "metric": metric.metric,
                "value": metric.value,
            }
            for metric in metrics
        )
    registered = tuple(catalog.register_manifests(manifests))
    ranking = rank_walk_forward_candidates(
        pd.DataFrame(metric_rows), scheme, metric="net_excess_annual_return"
    )
    selected_name = str(ranking.iloc[0]["candidate"])
    summary = ConsensusCohortSummary(
        attempted=len(schemes),
        selected_name=selected_name,
        selected_run_id=specs[selected_name].run_id,
        registered_run_ids=registered,
    )
    return summary, ranking


def _consensus_weight_schemes(
    names: list[str],
    turnovers: dict[str, float],
) -> dict[str, dict[str, float]]:
    equal = {name: 1.0 / len(names) for name in names}
    core = [name for name in names if "revision_only" in name]
    if len(core) != 2:
        raise ValueError("Expected two revision-only core consensus members.")
    core_equal = {name: (0.5 if name in core else 0.0) for name in names}
    core_satellite = {
        name: (0.4 if name in core else 0.2 / (len(names) - len(core)))
        for name in names
    }
    inverse = {name: 1.0 / turnovers[name] for name in names}
    total = sum(inverse.values())
    inverse = {name: value / total for name, value in inverse.items()}
    return {
        "equal_all": equal,
        "core_revision_equal": core_equal,
        "core80_satellite20": core_satellite,
        "inverse_turnover": inverse,
    }


def _evaluate_crossed_target(
    target: pd.DataFrame,
    returns: pd.DataFrame,
    costs: AsymmetricCostContract,
) -> tuple[pd.Series, pd.Series, list[MetricValue]]:
    gross = (target * returns.fillna(0.0)).sum(axis=1)
    zero = pd.Series(0.0, index=target.index)
    breakdown = costs.evaluate_netted_orders(
        stock_target=target,
        stock_pretrade=target.shift(1).fillna(0.0),
        etf_target=zero,
        etf_pretrade=zero,
    )
    net = gross - breakdown["total_trade_cost"]
    turnover = breakdown["stock_buy_turnover"] + breakdown["stock_sell_turnover"]
    return gross, net, [
        MetricValue(
            "historical_full", "annualized_turnover", float(turnover.mean() * 252)
        ),
        MetricValue(
            "historical_full",
            "annualized_trade_cost",
            float(breakdown["total_trade_cost"].mean() * 252),
        ),
    ]


def _member_turnovers(
    catalog: AlphaPoolCatalog,
    run_ids: list[str],
    names: list[str],
) -> dict[str, float]:
    metrics = catalog.metrics()
    rows = metrics.loc[
        metrics["run_id"].isin(run_ids)
        & metrics["segment"].eq("historical_full")
        & metrics["metric"].eq("annualized_turnover")
    ].set_index("run_id")["value"]
    missing = sorted(set(run_ids) - set(rows.index))
    if missing:
        raise ValueError(f"Selected consensus member is missing turnover: {missing}")
    return {
        name: float(rows.loc[run_id])
        for name, run_id in zip(names, run_ids, strict=True)
    }


def _load_artifact_frame(
    catalog: AlphaPoolCatalog,
    run_id: str,
    artifact_name: str,
) -> pd.DataFrame:
    rows = catalog.runs().set_index("run_id")
    relative = Path(str(rows.loc[run_id, "artifact_dir"]))
    path = (catalog.path.parent / relative / f"{artifact_name}.parquet").resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_parquet(path)


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
