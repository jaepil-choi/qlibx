from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from qlib_extended.research.config import read_yaml_mapping, require_mapping, require_string
from qlib_extended.research.pool import AlphaPoolCatalog


@dataclass(frozen=True)
class LeaderboardConfig:
    path: Path
    portfolio_key: str
    selection_generation: int
    maximum_rebalance_days: int
    minimum_positive_fraction: float
    minimum_annual_net_excess: float
    minimum_cumulative_relative_wealth_excess: float
    required_families: tuple[str, ...]
    leaderboard_size: int
    worst_fold_weight: float
    mean_fold_weight: float
    historical_manifest: Path
    historical_status: str

    @classmethod
    def from_yaml(cls, path: Path, *, integration_root: Path) -> LeaderboardConfig:
        payload = read_yaml_mapping(path)
        if payload.get("schema_version") != 1:
            raise ValueError("Leaderboard schema_version must be 1.")
        eligible = require_mapping(payload.get("eligible"), "eligible")
        ranking = require_mapping(eligible.get("ranking"), "eligible.ranking")
        historical = require_mapping(payload.get("historical"), "historical")
        families = eligible.get("required_families")
        if not isinstance(families, list) or not families:
            raise ValueError("eligible.required_families must be a non-empty list.")
        config = cls(
            path=path.resolve(),
            portfolio_key=require_string(
                eligible.get("portfolio_key"), "eligible.portfolio_key"
            ),
            selection_generation=int(eligible["selection_generation"]),
            maximum_rebalance_days=int(eligible["maximum_rebalance_days"]),
            minimum_positive_fraction=float(eligible["minimum_positive_fraction"]),
            minimum_annual_net_excess=float(eligible["minimum_annual_net_excess"]),
            minimum_cumulative_relative_wealth_excess=float(
                eligible["minimum_cumulative_relative_wealth_excess"]
            ),
            required_families=tuple(str(item) for item in families),
            leaderboard_size=int(eligible["leaderboard_size"]),
            worst_fold_weight=float(ranking["worst_fold_weight"]),
            mean_fold_weight=float(ranking["mean_fold_weight"]),
            historical_manifest=(
                integration_root / require_string(
                    historical.get("source_manifest"), "historical.source_manifest"
                )
            ).resolve(),
            historical_status=require_string(
                historical.get("status"), "historical.status"
            ),
        )
        if config.selection_generation < 0 or config.maximum_rebalance_days > 63:
            raise ValueError("Eligible leaderboard generation/interval is invalid.")
        if config.leaderboard_size < 1:
            raise ValueError("eligible.leaderboard_size must be positive.")
        if abs(config.worst_fold_weight + config.mean_fold_weight - 1.0) > 1e-12:
            raise ValueError("Leaderboard ranking weights must sum to one.")
        return config


@dataclass(frozen=True)
class LeaderboardBuildResult:
    eligible: pd.DataFrame
    historical: pd.DataFrame
    audit: Mapping[str, Any]


def build_leaderboards(
    catalog: AlphaPoolCatalog,
    config: LeaderboardConfig,
) -> LeaderboardBuildResult:
    runs = catalog.runs()
    prefix = f"{config.portfolio_key}.trial."
    candidates = runs.loc[
        runs["alpha_key"].str.startswith(prefix, na=False)
        & runs["status"].eq("complete")
        & runs["research_track"].eq("trusted")
        & runs["rebalance_days"].le(config.maximum_rebalance_days)
    ].copy()
    provenance: dict[str, Mapping[str, Any]] = {}
    for row in candidates.itertuples(index=False):
        manifest = _read_run_manifest(catalog, str(row.artifact_dir))
        run_provenance = manifest.get("provenance", {})
        if not isinstance(run_provenance, dict):
            raise ValueError(f"Invalid provenance for {row.run_id}")
        provenance[str(row.run_id)] = run_provenance
    eligible = rank_eligible_candidates(
        candidates,
        catalog.metrics(),
        provenance,
        config=config,
    )
    selection_key = (
        f"{config.portfolio_key}.selection.generation_{config.selection_generation}"
    )
    selection = runs.loc[runs["alpha_key"].eq(selection_key)]
    if len(selection) != 1:
        raise ValueError(f"Expected one trusted physical selection: {selection_key}")
    selected_manifest = _read_run_manifest(
        catalog, str(selection.iloc[0]["artifact_dir"])
    )
    selected_trial = selected_manifest["provenance"]["selected_trial"]
    if not isinstance(selected_trial, dict):
        raise ValueError("Physical selection is missing selected_trial provenance.")
    selected_candidate = _physical_trial_name(selected_trial)
    if eligible.empty:
        raise ValueError("No candidate passes the eligible leaderboard gates.")
    expected = eligible.iloc[0]["candidate"]
    if expected != selected_candidate:
        raise ValueError(
            "Leaderboard rank one differs from immutable physical selection: "
            f"{expected}; {selected_candidate}"
        )
    goal_passing_count = len(eligible)
    eligible = eligible.head(config.leaderboard_size).copy()
    eligible.insert(0, "rank", range(1, len(eligible) + 1))
    eligible.insert(1, "status", ["Champion", *["Eligible"] * (len(eligible) - 1)])
    historical = load_historical_medals(config)
    audit = {
        "selection_generation": config.selection_generation,
        "complete_physical_trials_all_generations": int(len(candidates)),
        "generation_candidates": int(
            sum(
                int(item.get("retry_generation", -1))
                == config.selection_generation
                for item in provenance.values()
            )
        ),
        "goal_passing_candidates": int(goal_passing_count),
        "selection_run_id": str(selection.iloc[0]["run_id"]),
        "true_forward_oos": bool(
            selected_manifest.get("provenance", {}).get("true_forward_oos", False)
        ),
    }
    return LeaderboardBuildResult(eligible=eligible, historical=historical, audit=audit)


def rank_eligible_candidates(
    runs: pd.DataFrame,
    metrics: pd.DataFrame,
    provenance: Mapping[str, Mapping[str, Any]],
    *,
    config: LeaderboardConfig,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for run in runs.itertuples(index=False):
        run_id = str(run.run_id)
        prov = provenance.get(run_id, {})
        if int(prov.get("retry_generation", -1)) != config.selection_generation:
            continue
        resolved = prov.get("resolved_config")
        if not isinstance(resolved, dict):
            raise ValueError(f"Missing resolved_config for {run_id}")
        allocation = resolved.get("allocation")
        if not isinstance(allocation, dict):
            raise ValueError(f"Missing family allocation for {run_id}")
        if any(
            float(allocation.get(family, 0.0)) <= 0.0
            for family in config.required_families
        ):
            continue
        run_metrics = metrics.loc[metrics["run_id"].eq(run_id)]
        full = run_metrics.loc[run_metrics["segment"].eq("historical_full")].set_index(
            "metric"
        )["value"]
        required = {
            "net_excess_annual_return",
            "cumulative_benchmark_excess",
            "annualized_trade_cost",
        }
        if not required.issubset(full.index):
            raise ValueError(
                f"Eligible metrics missing for {run_id}: {required - set(full.index)}"
            )
        folds = run_metrics.loc[
            run_metrics["segment"].str.startswith("walk_forward_", na=False)
            & run_metrics["metric"].eq("net_excess_annual_return"),
            "value",
        ]
        if folds.empty:
            raise ValueError(f"Walk-forward folds missing for {run_id}")
        positive_fraction = float(folds.gt(0.0).mean())
        annual = float(full.loc["net_excess_annual_return"])
        cumulative = float(full.loc["cumulative_benchmark_excess"])
        if (
            positive_fraction < config.minimum_positive_fraction
            or annual < config.minimum_annual_net_excess
            or cumulative < config.minimum_cumulative_relative_wealth_excess
        ):
            continue
        worst = float(folds.min())
        mean = float(folds.mean())
        rows.append(
            {
                "run_id": run_id,
                "candidate": str(run.alpha_key).removeprefix(
                    f"{config.portfolio_key}.trial."
                ),
                "annual_net_excess": annual,
                "cumulative_relative_wealth_excess": cumulative,
                "positive_folds": int(folds.gt(0.0).sum()),
                "fold_count": int(len(folds)),
                "worst_fold": worst,
                "mean_fold": mean,
                "annualized_trade_cost": float(full.loc["annualized_trade_cost"]),
                "rebalance_days": int(run.rebalance_days),
                "selection_score": (
                    config.worst_fold_weight * worst
                    + config.mean_fold_weight * mean
                ),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["selection_score", "annual_net_excess", "candidate"],
        ascending=[False, False, True],
        ignore_index=True,
    )


def load_historical_medals(config: LeaderboardConfig) -> pd.DataFrame:
    payload = json.loads(config.historical_manifest.read_text(encoding="utf-8"))
    leaders = payload.get("leaders")
    if not isinstance(leaders, list) or len(leaders) != 3:
        raise ValueError("Historical leaderboard must preserve exactly three medals.")
    return pd.DataFrame(
        {
            "medal": [str(item["medal"]) for item in leaders],
            "trial": [str(item["trial"]) for item in leaders],
            "annual_net_excess": [float(item["full_net_active_return"]) for item in leaders],
            "information_ratio": [float(item["full_net_information_ratio"]) for item in leaders],
            "cumulative_relative_wealth_excess": [
                float(item["cumulative_relative_wealth_excess"]) for item in leaders
            ],
            "status": [config.historical_status] * len(leaders),
        }
    )


def render_eligible_markdown(frame: pd.DataFrame, audit: Mapping[str, Any]) -> str:
    rows = [
        "# Eligible trusted physical leaderboard",
        "",
        "| 순위 | 상태 | 후보 | 연 net excess | 누적 relative wealth | 양수 fold | 연 비용 |",
        "|---:|---|---|---:|---:|---:|---:|",
    ]
    for item in frame.itertuples(index=False):
        rows.append(
            f"| {item.rank} | {item.status} | `{item.candidate}` | "
            f"{item.annual_net_excess:.3%} | "
            f"{item.cumulative_relative_wealth_excess:.3%} | "
            f"{item.positive_folds}/{item.fold_count} | "
            f"{item.annualized_trade_cost:.3%} |"
        )
    rows.extend(
        [
            "",
            f"- selection generation: {audit['selection_generation']}",
            f"- generation trials / goal passing: {audit['generation_candidates']} / {audit['goal_passing_candidates']}",
            f"- true forward OOS: {str(audit['true_forward_oos']).lower()}",
            "- 비용은 cross-family physical netting 이후 한 번만 적용했다.",
            "",
        ]
    )
    return "\n".join(rows)


def render_historical_markdown(frame: pd.DataFrame) -> str:
    rows = [
        "# Historical Gold / Silver / Bronze",
        "",
        "| Medal | Trial | 연 net excess | IR | Relative wealth | Status |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in frame.itertuples(index=False):
        rows.append(
            f"| {item.medal} | `{item.trial}` | {item.annual_net_excess:.3%} | "
            f"{item.information_ratio:.3f} | "
            f"{item.cumulative_relative_wealth_excess:.3%} | `{item.status}` |"
        )
    rows.extend(
        [
            "",
            "이 medal은 기존 기록을 그대로 보존한다. Financial 252일 proxy와 historical-prior-informed selection을 포함하므로 신규 trusted champion 선정에는 참여하지 않는다.",
            "",
        ]
    )
    return "\n".join(rows)


def _read_run_manifest(catalog: AlphaPoolCatalog, artifact_dir: str) -> dict[str, Any]:
    path = (catalog.path.parent / artifact_dir / "manifest.json").resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid manifest payload: {path}")
    return payload


def _physical_trial_name(selected_trial: Mapping[str, Any]) -> str:
    allocation = selected_trial.get("allocation")
    if not isinstance(allocation, dict):
        raise ValueError("selected_trial allocation is missing.")
    return (
        f"mkt{float(allocation['market']):.2f}_con{float(allocation['consensus']):.2f}"
        f"__etf{float(selected_trial['target_etf_sleeve']):.2f}"
        f"__a{float(selected_trial['alpha_multiplier']):.2f}"
        f"__fin{float(selected_trial['financing_budget']):.2f}"
    )
