from __future__ import annotations

from pathlib import Path

import pandas as pd

from qlib_extended.research.leaderboard import (
    LeaderboardConfig,
    load_historical_medals,
    rank_eligible_candidates,
    render_eligible_markdown,
)


ROOT = Path(__file__).resolve().parents[1]


def _config() -> LeaderboardConfig:
    return LeaderboardConfig.from_yaml(
        ROOT / "configs" / "leaderboards" / "trusted-physical.yaml",
        integration_root=ROOT,
    )


def test_historical_medals_preserve_gold_silver_bronze() -> None:
    frame = load_historical_medals(_config())

    assert frame["medal"].tolist() == ["Gold", "Silver", "Bronze"]
    assert frame["annual_net_excess"].round(6).tolist() == [
        0.01279,
        0.012626,
        0.012594,
    ]
    assert set(frame["status"]) == {"deprecated_historical_prior_informed"}


def test_eligible_ranking_applies_generation_and_performance_gates() -> None:
    runs = pd.DataFrame(
        [
            {
                "run_id": "winner",
                "alpha_key": (
                    "portfolio.trusted_market_consensus.physical.trial.winner"
                ),
                "rebalance_days": 1,
            },
            {
                "run_id": "old",
                "alpha_key": "portfolio.trusted_market_consensus.physical.trial.old",
                "rebalance_days": 1,
            },
        ]
    )
    metric_rows = []
    for run_id, annual, cumulative, folds in (
        ("winner", 0.0114, 0.0711, [-0.01, 0.02, 0.03, 0.04]),
        ("old", 0.0200, 0.1500, [0.01, 0.02, 0.03, 0.04]),
    ):
        metric_rows.extend(
            [
                {
                    "run_id": run_id,
                    "segment": "historical_full",
                    "metric": "net_excess_annual_return",
                    "value": annual,
                },
                {
                    "run_id": run_id,
                    "segment": "historical_full",
                    "metric": "cumulative_benchmark_excess",
                    "value": cumulative,
                },
                {
                    "run_id": run_id,
                    "segment": "historical_full",
                    "metric": "annualized_trade_cost",
                    "value": 0.01,
                },
            ]
        )
        metric_rows.extend(
            {
                "run_id": run_id,
                "segment": f"walk_forward_{index}",
                "metric": "net_excess_annual_return",
                "value": value,
            }
            for index, value in enumerate(folds)
        )
    provenance = {
        "winner": {
            "retry_generation": 3,
            "resolved_config": {
                "allocation": {"market": 0.65, "consensus": 0.35}
            },
        },
        "old": {
            "retry_generation": 2,
            "resolved_config": {
                "allocation": {"market": 0.75, "consensus": 0.25}
            },
        },
    }

    ranked = rank_eligible_candidates(
        runs, pd.DataFrame(metric_rows), provenance, config=_config()
    )

    assert ranked["run_id"].tolist() == ["winner"]
    markdown = render_eligible_markdown(
        ranked.assign(rank=[1], status=["Champion"]),
        {
            "selection_generation": 3,
            "generation_candidates": 40,
            "goal_passing_candidates": 4,
            "true_forward_oos": False,
        },
    )
    assert "1.140%" in markdown
