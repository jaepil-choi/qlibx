from __future__ import annotations

from pathlib import Path

import pandas as pd

from qlibx import Project
from qlibx.data import (
    CapabilityPlan,
    CapabilityRequirements,
    ConfigDrivenDataLoader,
    execution_profile_requirements,
    plan_execution_profile,
)


def test_repository_daily_close_profile_maps_event_date_and_availability() -> None:
    root = Path(__file__).parents[1]
    project = Project.load(root)
    declaration = execution_profile_requirements()
    assert isinstance(declaration, CapabilityRequirements)
    assert declaration.capability_id == "qlibx.execution.daily_close"
    assert {item.role for item in declaration.requirements} >= {
        "execution_price",
        "valuation_price",
        "benchmark_weight",
    }
    plan = plan_execution_profile(project)
    assert isinstance(plan, CapabilityPlan)
    assert plan.ready is True
    assert plan.parameters["clock"]["signal_cutoff"] == "t_minus_1_close"
    role_contracts = plan.parameters["role_contracts"]
    assert role_contracts["execution_price"]["event_time_field"] == "event_date"
    assert role_contracts["execution_price"]["availability_field"] == "available_at"
    assert plan.parameters["derived_fields"] == []
    assert "correction" not in str(plan.parameters["roles"]).lower()
    assert plan.resolution.missing_requirements == ()


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
