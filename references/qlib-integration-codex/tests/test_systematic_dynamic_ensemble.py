from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from qlib_extended.research.dynamic_ensemble import (
    SUPPORTED_RULES,
    DynamicAllocationSpec,
    allocation_turnover,
    build_causal_allocation,
    combine_targets,
)

ROOT = Path(__file__).resolve().parents[1]


def sample_returns() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        rng.normal(
            loc=[0.0004, 0.0002, 0.0001],
            scale=[0.006, 0.004, 0.003],
            size=(420, 3),
        ),
        index=pd.bdate_range("2024-01-02", periods=420),
        columns=["market", "consensus", "financial"],
    )


@pytest.mark.parametrize("rule", SUPPORTED_RULES)
def test_dynamic_allocation_is_long_only_and_fully_allocated(rule: str) -> None:
    returns = sample_returns()
    turnover = pd.DataFrame(
        0.01,
        index=returns.index,
        columns=returns.columns,
    )
    allocation = build_causal_allocation(
        returns,
        DynamicAllocationSpec(name=rule, rule=rule),
        turnover=turnover,
    )

    assert allocation.ge(0.0).all().all()
    assert np.allclose(allocation.sum(axis=1), 1.0)
    changed = allocation.diff().abs().sum(axis=1).gt(1e-12)
    assert set(np.flatnonzero(changed.to_numpy())).issubset(set(range(63, 420, 63)))


def test_dynamic_allocation_does_not_use_future_returns() -> None:
    returns = sample_returns()
    changed_future = returns.copy()
    changed_future.iloc[300:] *= -50.0
    spec = DynamicAllocationSpec(name="momentum", rule="momentum")

    original = build_causal_allocation(returns, spec)
    perturbed = build_causal_allocation(changed_future, spec)

    pd.testing.assert_frame_equal(original.iloc[:301], perturbed.iloc[:301])


def test_minimum_variance_turnover_penalty_reduces_weight_churn() -> None:
    returns = sample_returns()
    minimum_variance = build_causal_allocation(
        returns,
        DynamicAllocationSpec(
            name="minimum_variance_turnover",
            rule="minimum_variance_turnover",
        ),
    )
    momentum = build_causal_allocation(
        returns,
        DynamicAllocationSpec(name="momentum", rule="momentum"),
    )

    assert allocation_turnover(minimum_variance).sum() < allocation_turnover(
        momentum
    ).sum()


def test_combine_targets_uses_time_varying_family_allocation() -> None:
    dates = pd.bdate_range("2026-01-02", periods=2)
    columns = ["A", "B"]
    targets = {
        "market": pd.DataFrame([[1.0, -1.0], [1.0, -1.0]], dates, columns),
        "financial": pd.DataFrame([[-1.0, 1.0], [-1.0, 1.0]], dates, columns),
    }
    allocation = pd.DataFrame(
        [[0.75, 0.25], [0.25, 0.75]],
        dates,
        ["market", "financial"],
    )

    combined = combine_targets(targets, allocation)

    expected = pd.DataFrame([[0.5, -0.5], [-0.5, 0.5]], dates, columns)
    pd.testing.assert_frame_equal(combined, expected)


def test_final_three_family_config_has_no_weight_grid_and_five_plus_ideas() -> None:
    config = yaml.safe_load(
        (
            ROOT
            / "configs"
            / "portfolio"
            / "dynamic-market-consensus-financial.yaml"
        ).read_text(encoding="utf-8")
    )

    assert config["governance"]["family_weight_grid"] is False
    assert len(config["allocation"]["ideas"]) >= 5
    assert len(set(config["allocation"]["ideas"])) == len(
        config["allocation"]["ideas"]
    )
    assert "family_allocations" not in config["allocation"]
    assert config["members"]["financial_alpha_key"].endswith(
        "minimum_variance_turnover"
    )
