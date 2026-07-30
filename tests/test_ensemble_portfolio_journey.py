from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from qlibx import Project, QlibxError
from qlibx.ensemble import combine_stored_weights
from qlibx.portfolio import construct_enhanced_index
from qlibx.research import ResearchCatalog


def _store_member(
    catalog: ResearchCatalog,
    session: str,
    weights: pd.DataFrame,
    counter: list[str],
) -> str:
    counter.append(session)
    attempt = catalog.begin(
        session_id=session,
        invocation={"strategy": session},
        kind="alpha_run",
    )
    catalog.stage_frame(attempt, "weights", weights)
    return catalog.publish(attempt, status="successful", metadata={}).record_id


def test_verified_stored_ensemble_does_not_rerun_members_and_preserves_flexible_exposure(
    tmp_path: Path,
) -> None:
    catalog = ResearchCatalog.from_project(Project.initialize(tmp_path))
    dates = pd.DatetimeIndex(["2025-01-02"])
    calls: list[str] = []
    first = _store_member(
        catalog,
        "first",
        pd.DataFrame([[0.20, -0.10]], index=dates, columns=["A", "B"]),
        calls,
    )
    second = _store_member(
        catalog,
        "second",
        pd.DataFrame([[-0.10, 0.05]], index=dates, columns=["A", "C"]),
        calls,
    )
    before = tuple(calls)
    result = combine_stored_weights(catalog, members={first: 0.5, second: 0.5})
    assert tuple(calls) == before
    assert result.combined.loc[dates[0], "A"] == pytest.approx(0.05)
    assert result.combined.loc[dates[0], "B"] == pytest.approx(-0.05)
    assert result.combined.loc[dates[0], "C"] == pytest.approx(0.025)
    assert result.netting.loc[dates[0], "A"] == pytest.approx(0.10)
    assert result.netting.loc[dates[0], "B"] == pytest.approx(0.0)
    assert result.exposure.long.iloc[0] == pytest.approx(0.075)
    assert result.exposure.short.iloc[0] == pytest.approx(-0.05)
    assert result.parent_lineage == tuple(sorted((first, second)))
    assert set(result.member_similarity) == {first, second}
    assert sum(result.effective_weights.values()) == pytest.approx(1.0)


def test_stored_ensemble_preserves_compatible_event_and_ticker_axis_semantics(
    tmp_path: Path,
) -> None:
    catalog = ResearchCatalog.from_project(Project.initialize(tmp_path))
    calls: list[str] = []
    weights = pd.DataFrame(
        [[0.1]],
        index=pd.DatetimeIndex(["2025-01-02"], name="event_date").as_unit("us"),
        columns=pd.Index(["A"], name="ticker"),
    )
    record_id = _store_member(catalog, "named", weights, calls)
    result = combine_stored_weights(catalog, members={record_id: 1.0})
    assert result.combined.index.name == "event_date"
    assert result.combined.columns.name == "ticker"
    assert str(result.combined.index.dtype) == "datetime64[us]"


def test_corrupt_stored_member_is_not_returned_as_verified(tmp_path: Path) -> None:
    catalog = ResearchCatalog.from_project(Project.initialize(tmp_path))
    calls: list[str] = []
    record_id = _store_member(
        catalog,
        "member",
        pd.DataFrame([[0.1]], index=pd.DatetimeIndex(["2025-01-02"]), columns=["A"]),
        calls,
    )
    manifest = catalog.list_results()[0]
    blob = catalog.blobs / manifest["artifacts"][0]["blob_digest"]
    blob.write_bytes(b"corrupt")
    with pytest.raises(QlibxError) as corrupt:
        combine_stored_weights(catalog, members={record_id: 1.0})
    assert corrupt.value.stage == "RESEARCH_RECORD"
    assert corrupt.value.context["record_id"] == record_id


def test_opaque_etf_is_physical_without_invented_lookthrough() -> None:
    result = construct_enhanced_index(
        benchmark_weight=pd.Series({"STOCK": 0.5, "ETF": 0.4}),
        active_weight=pd.Series({"STOCK": 0.05, "ETF": -0.05}),
        price=pd.Series({"STOCK": 10.0, "ETF": 20.0}),
        portfolio_value=2_000.0,
        instrument_type=pd.Series({"STOCK": "stock", "ETF": "etf"}),
        current_quantity=pd.Series({"STOCK": 100, "ETF": 40}),
        current_cash=200.0,
        transaction_cost=pd.Series({"STOCK": 0.001, "ETF": 0.0005}),
    )
    assert result.status == "soft_relaxed"
    assert result.lookthrough_exposure is None
    assert 0.54 <= result.physical_weight["STOCK"] < 0.55
    assert result.physical_weight["ETF"] == pytest.approx(0.35)
    assert result.etf_weight["ETF"] == pytest.approx(0.35)
    assert result.cash_weight == pytest.approx(0.105)
    assert result.expected_cost > 0
    assert result.solver_metadata["solver"] == "CLARABEL"
    assert result.solver_metadata["raw_status"] == "optimal"


def test_point_in_time_etf_lookthrough_is_separate_and_reports_solver_state() -> None:
    exposure = pd.DataFrame(
        {"STOCK_A": [1.0, 0.0], "ETF_AB": [0.5, 0.5]},
        index=["A", "B"],
    )
    result = construct_enhanced_index(
        benchmark_weight=pd.Series({"A": 0.5, "B": 0.4}),
        active_weight=pd.Series({"A": 0.1, "B": 0.0}),
        price=pd.Series({"STOCK_A": 10.0, "ETF_AB": 10.0}),
        portfolio_value=1_000.0,
        instrument_type=pd.Series({"STOCK_A": "stock", "ETF_AB": "etf"}),
        constituent_exposure=exposure,
        constituent_available_at=pd.Timestamp("2025-01-01"),
        decision_time=pd.Timestamp("2025-01-02"),
        tracking_tolerance=0.01,
        transaction_cost=pd.Series({"STOCK_A": 0.0, "ETF_AB": 0.0}),
    )
    assert result.status == "optimal"
    assert result.lookthrough_exposure is not None
    assert result.physical_weight.index.tolist() == ["STOCK_A", "ETF_AB"]
    assert result.lookthrough_exposure.index.tolist() == ["A", "B"]
    assert result.lookthrough_exposure["A"] == pytest.approx(0.6, abs=0.01)
    assert result.lookthrough_exposure["B"] == pytest.approx(0.4, abs=0.01)
    assert result.validation_passed is True
    assert result.tracking_error <= 0.01
    assert result.unimplemented_active_weight.abs().max() <= 0.01

    with pytest.raises(ValueError, match="not available"):
        construct_enhanced_index(
            benchmark_weight=pd.Series({"A": 0.5, "B": 0.4}),
            active_weight=pd.Series({"A": 0.1, "B": 0.0}),
            price=pd.Series({"STOCK_A": 10.0, "ETF_AB": 10.0}),
            portfolio_value=1_000.0,
            constituent_exposure=exposure,
            constituent_available_at=pd.Timestamp("2025-01-03"),
            decision_time=pd.Timestamp("2025-01-02"),
        )


def test_soft_residual_and_hard_infeasibility_are_distinct() -> None:
    soft = construct_enhanced_index(
        benchmark_weight=pd.Series({"A": 0.5, "B": 0.4}),
        active_weight=pd.Series({"A": 0.1, "B": 0.0}),
        price=pd.Series({"A": 10.0, "B": 10.0}),
        portfolio_value=1_000.0,
        tradable=pd.Series({"A": False, "B": True}),
    )
    assert soft.status == "soft_relaxed"
    assert "untradable:A" in soft.binding_constraints
    assert soft.unimplemented_active_weight["A"] == pytest.approx(0.1)
    assert soft.passive_residual["A"] == pytest.approx(0.5)

    hard = construct_enhanced_index(
        benchmark_weight=pd.Series({"A": 0.1}),
        active_weight=pd.Series({"A": -0.2}),
        price=pd.Series({"A": 10.0}),
        portfolio_value=1_000.0,
    )
    assert hard.status == "hard_infeasible"
    assert hard.validation_passed is False
    assert "negative" in hard.reason
