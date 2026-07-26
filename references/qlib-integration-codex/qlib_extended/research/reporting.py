from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPORT_SELECTION_KEY = (
    "portfolio.dynamic_market_consensus_financial_generation_2.physical.stretch."
    "minimum_variance_momentum__family_breadth_conviction"
)
REPORT_STATUS = (
    "HISTORICAL_SELECTION_NOT_TRUE_FORWARD_OOS_FINANCIAL_EXACT_PIT_UNAVAILABLE"
)


def validate_systematic_report_bundle(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    report_dir = root / "docs" / "report" / "enhanced-index-2"
    assets = report_dir / "report-assets"
    manifest = json.loads((assets / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != REPORT_STATUS:
        raise ValueError("Systematic report status differs from report contract.")
    if manifest.get("final_method_key") != REPORT_SELECTION_KEY:
        raise ValueError("Systematic report selection differs from report contract.")
    financial_members = [
        member
        for member in manifest.get("members", [])
        if member.get("family") == "financial"
    ]
    if len(financial_members) != 1:
        raise ValueError("Systematic report must contain one financial family member.")
    financial_member = financial_members[0]
    if (
        financial_member.get("status") != "selected_exact_pit_unavailable"
        or float(financial_member.get("mean_weight", 0.0)) <= 0.0
    ):
        raise ValueError(
            "Systematic report financial member must have positive weight and "
            "declare that exact PIT filing vintage is unavailable."
        )
    date_range = manifest.get("date_range", {})
    if date_range != {
        "start": "2018-01-02",
        "end": "2026-07-20",
        "observations": 2096,
    }:
        raise ValueError("Systematic report date range differs from contract.")
    selection_relative = Path(manifest["source_paths"]["selection_artifact"])
    selection_path = root / "qlib-integration-codex" / "research" / selection_relative
    daily = pd.read_parquet(selection_path)
    expected = {
        "annualized_gross_excess_return": float(
            daily["gross_excess_return"].mean() * 252.0
        ),
        "annualized_trade_cost": float(daily["total_trade_cost"].mean() * 252.0),
        "annualized_net_excess_return": float(
            daily["net_excess_return"].mean() * 252.0
        ),
        "net_information_ratio": _information_ratio(daily["net_excess_return"]),
        "cumulative_gross_excess_sum": float(daily["gross_excess_return"].sum()),
        "cumulative_net_excess_sum": float(daily["net_excess_return"].sum()),
        "cumulative_relative_wealth_excess": _relative_wealth(daily),
        "tracking_error": float(
            daily["net_excess_return"].std(ddof=1) * np.sqrt(252.0)
        ),
    }
    final_result = manifest.get("final_result", {})
    errors = {
        key: abs(float(final_result.get(key, np.nan)) - value)
        for key, value in expected.items()
    }
    if max(errors.values()) > 1e-12:
        raise ValueError(f"Systematic report KPI mismatch: {errors}")
    missing_assets = []
    for relative in manifest.get("figures", {}).values():
        if not (assets / relative).is_file():
            missing_assets.append(str(relative))
    for relative in manifest.get("tables", {}).values():
        if not (assets / relative).is_file():
            missing_assets.append(str(relative))
    if missing_assets:
        raise FileNotFoundError(f"Systematic report assets missing: {missing_assets}")
    calendar = pd.read_csv(assets / manifest["tables"]["table_01"])
    expected_calendar_columns = [
        "period",
        "gross_excess_sum",
        "gross_information_ratio",
        "trade_cost_sum",
        "net_excess_sum",
        "net_information_ratio",
    ]
    if list(calendar.columns) != expected_calendar_columns:
        raise ValueError("Systematic report calendar table columns differ from contract.")
    full_period = calendar.loc[calendar["period"].eq("full_period_cumulative")]
    if len(full_period) != 1:
        raise ValueError("Systematic report calendar table must contain one full period row.")
    full_period_expected = {
        "gross_excess_sum": expected["cumulative_gross_excess_sum"],
        "gross_information_ratio": _information_ratio(
            daily["gross_excess_return"]
        ),
        "trade_cost_sum": float(daily["total_trade_cost"].sum()),
        "net_excess_sum": expected["cumulative_net_excess_sum"],
        "net_information_ratio": expected["net_information_ratio"],
    }
    full_period_errors = {
        key: abs(float(full_period.iloc[0][key]) - value)
        for key, value in full_period_expected.items()
    }
    if max(full_period_errors.values()) > 1e-12:
        raise ValueError(
            f"Systematic report calendar KPI mismatch: {full_period_errors}"
        )
    markdown = (report_dir / "report-draft-3.md").read_text(encoding="utf-8")
    required_text = (
        "2018년 1월 2일~2026년 7월 20일",
        "KOSPI 200 지수 대비 누적 초과수익과 고점 대비 하락률",
        "비용 전 IR",
        "$IC$(정보계수)",
        "$TC$(신호 전달계수)",
        "true forward OOS가 아니다",
    )
    missing_text = [text for text in required_text if text not in markdown]
    if missing_text:
        raise ValueError(f"Systematic report text is stale: {missing_text}")
    return {
        "status": "PASS",
        "selection_run_id": manifest["selection_run_id"],
        "final_method_key": manifest["final_method_key"],
        "figure_count": len(manifest["figures"]),
        "table_count": len(manifest["tables"]),
        "max_kpi_error": max(errors.values()),
        "financial_pit_verified": False,
        "true_forward_oos": False,
    }


def _information_ratio(series: pd.Series) -> float:
    annual = float(series.mean() * 252.0)
    volatility = float(series.std(ddof=1) * np.sqrt(252.0))
    return annual / volatility


def _relative_wealth(daily: pd.DataFrame) -> float:
    portfolio = float((1.0 + daily["net_portfolio_return"]).prod())
    benchmark = float((1.0 + daily["benchmark_return"]).prod())
    return portfolio / benchmark - 1.0
