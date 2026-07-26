from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from qlib_extended.research import (
    PhysicalPortfolioConfig,
    benchmark_scale_active_target,
    project_benchmark_neutral,
    project_direct_stock,
)


ROOT = Path(__file__).resolve().parents[1]


def test_physical_search_grid_is_bounded_and_keeps_etf_floor() -> None:
    config = PhysicalPortfolioConfig.from_yaml(
        ROOT / "configs" / "portfolio" / "trusted-market-consensus.yaml"
    )
    specs = config.trial_specs()

    assert len(specs) == 135
    assert config.retry_generation == 1
    assert {spec.target_etf_sleeve for spec in specs} == {0.3, 0.4, 0.5}
    assert {spec.alpha_multiplier for spec in specs} == {0.05, 0.1, 0.2}
    assert min(spec.realized_etf_sleeve for spec in specs) >= 0.10 - 1e-12
    assert sum(not spec.allocation.control_only for spec in specs) == 81


def test_boundary_tuning_grid_is_frozen_to_40_trials() -> None:
    config = PhysicalPortfolioConfig.from_yaml(
        ROOT
        / "configs"
        / "portfolio"
        / "trusted-market-consensus-boundary-tuning.yaml"
    )
    specs = config.trial_specs()

    assert config.retry_generation == 3
    assert len(specs) == 40
    assert {spec.financing_budget for spec in specs} == {0.0}
    assert {spec.target_etf_sleeve for spec in specs} == {0.45, 0.50}
    assert {spec.alpha_multiplier for spec in specs} == {0.20, 0.22, 0.25, 0.30}
    assert all(not spec.allocation.control_only for spec in specs)


def test_direct_projection_is_long_only_capped_and_fully_invested() -> None:
    dates = pd.DatetimeIndex(["2026-01-02", "2026-01-05"])
    columns = ["A", "B", "C"]
    desired = pd.DataFrame(
        [[0.90, -0.20, 0.10], [0.01, 0.30, 0.09]],
        index=dates,
        columns=columns,
    )
    cap = pd.DataFrame(0.50, index=dates, columns=columns)
    fallback = pd.DataFrame(
        [[0.5, 0.3, 0.2], [0.5, 0.3, 0.2]], index=dates, columns=columns
    )

    projected = project_direct_stock(
        desired,
        mass=0.60,
        cap=cap,
        fallback=fallback,
    )

    assert np.allclose(projected.sum(axis=1), 0.60)
    assert projected.ge(0.0).all().all()
    assert projected.le(cap + 1e-12).all().all()


def test_benchmark_projection_removes_source_family_net_residual() -> None:
    dates = pd.DatetimeIndex(["2026-01-02"])
    target = pd.DataFrame([[0.20, -0.10, 0.05]], index=dates, columns=list("ABC"))
    benchmark = pd.DataFrame([[0.50, 0.30, 0.20]], index=dates, columns=list("ABC"))

    projected = project_benchmark_neutral(target, benchmark)

    assert projected.sum(axis=1).abs().max() < 1e-12
    expected = target - benchmark * target.sum(axis=1).iloc[0]
    pd.testing.assert_frame_equal(projected, expected)


def test_benchmark_scaled_target_is_zero_net_and_normalized() -> None:
    dates = pd.DatetimeIndex(["2026-01-02", "2026-01-05"])
    target = pd.DataFrame(
        [[0.20, -0.10, 0.00], [0.00, 0.00, 0.00]],
        index=dates,
        columns=list("ABC"),
    )
    benchmark = pd.DataFrame(
        [[0.50, 0.30, 0.20], [0.50, 0.30, 0.20]],
        index=dates,
        columns=list("ABC"),
    )

    scaled = benchmark_scale_active_target(target, benchmark, target_gross=2.0)

    assert scaled.sum(axis=1).abs().max() < 1e-12
    assert np.isclose(scaled.iloc[0].abs().sum(), 2.0)
    assert np.isclose(scaled.iloc[1].abs().sum(), 0.0)
