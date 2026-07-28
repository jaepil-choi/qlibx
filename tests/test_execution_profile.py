from __future__ import annotations

from pathlib import Path

import pandas as pd

from qlibx import Project
from qlibx.data import ConfigDrivenDataLoader, plan_execution_profile


def test_repository_daily_close_profile_maps_event_date_and_availability() -> None:
    root = Path(__file__).parents[1]
    project = Project.load(root)
    plan = plan_execution_profile(project)
    assert plan.ready is True
    assert plan.clock["signal_cutoff"] == "t_minus_1_close"
    assert plan.role_contracts["execution_price"]["event_time_field"] == "event_date"
    assert plan.role_contracts["execution_price"]["availability_field"] == "available_at"
    assert plan.derived_fields == ()
    assert "correction" not in str(plan.roles).lower()


def test_real_execution_matrix_indexes_event_date_with_prior_availability() -> None:
    root = Path(__file__).parents[1]
    loader = ConfigDrivenDataLoader.from_project(Project.load(root))
    matrix = loader.load_matrix(
        "execution_price",
        start="2025-01-02",
        end="2025-01-03",
        as_of="2025-01-01",
        tickers=["A005930"],
    )
    assert matrix.index.min() >= pd.Timestamp("2025-01-02")
    assert matrix.index.max() <= pd.Timestamp("2025-01-03")
    assert pd.Timestamp("2025-01-03") not in matrix.index
