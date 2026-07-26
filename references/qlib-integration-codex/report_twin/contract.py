from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


MARKET_PRICE_MEMBERS = (
    "peer_momentum",
    "open_close_rebound",
    "gap_exhaustion",
    "ranked_information_drift",
)
FINANCIAL_MEMBERS = (
    "high_leverage",
    "high_inventory_intensity",
    "low_depreciation_intensity",
    "low_lease_liability_intensity",
    "slow_low_lease_liability_intensity",
)
CONSENSUS_MEMBERS = (
    "eps_revision_20d",
    "net_income_12m_revision_20d",
    "net_income_fy1_revision_20d",
    "fy1_sales_revision_20d",
    "fy1_adjusted_op_revision_20d",
    "fy1_controlling_net_income_revision_20d",
    "fy1_net_income_revision_20d",
    "fy1_margin_revision_20d",
)
MEMBER_NAMES = (
    *MARKET_PRICE_MEMBERS,
    "high_free_float_ratio",
    "high_leverage",
    "low_depreciation_intensity",
    "low_lease_liability_intensity",
    "high_inventory_intensity",
    "slow_low_lease_liability_intensity",
    *CONSENSUS_MEMBERS,
)
FAMILY_NAMES = ("market_family", "financial_family", "consensus_revision_family")
RATIONALE_METHODS = (
    "rationale_equal_weight",
    "rationale_inverse_volatility",
    "rationale_inverse_turnover",
    "rationale_risk_adjusted_momentum_rank",
    "rationale_cost_aware_risk_parity",
)
MARKET_METHODS = (
    "equal_weight",
    "downside_adjusted_return_momentum",
    "trailing_return_rank",
    "risk_adjusted_return_momentum",
    "dual_horizon_rank_momentum",
    "trailing_return_momentum",
)
FINAL_METHOD = "rationale_inverse_volatility"
TOLERANCE = 1e-10


@dataclass(frozen=True)
class ReportInputs:
    project_root: Path
    manifest: dict[str, Any]
    realized_return: pd.DataFrame
    benchmark_weight: pd.DataFrame
    universe: pd.DataFrame
    members: dict[str, pd.DataFrame]
    source_paths: dict[str, Path]
    final_dir: Path
    price_cache: Path


def load_report_inputs(project_root: Path) -> ReportInputs:
    root = project_root.resolve()
    manifest_path = root / "docs/report/enhanced-index-2/report-assets/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_manifest(manifest)
    raw_paths = {name: root / Path(value) for name, value in manifest["source_paths"].items()}
    required = ("realized", "benchmark", "universe", *MEMBER_NAMES)
    missing_keys = sorted(set(required).difference(raw_paths))
    if missing_keys:
        raise ValueError(f"report manifest source paths are missing: {missing_keys}")
    missing_files = [str(raw_paths[name]) for name in required if not raw_paths[name].is_file()]
    if missing_files:
        raise FileNotFoundError(f"report twin inputs are missing: {missing_files}")

    realized = pd.read_parquet(raw_paths["realized"]).astype("float64")
    start = pd.Timestamp(manifest["date_range"]["start"])
    end = pd.Timestamp(manifest["date_range"]["end"])
    realized = realized.loc[(realized.index >= start) & (realized.index <= end)]
    if len(realized) != int(manifest["date_range"]["observations"]):
        raise ValueError("report manifest observation count differs from realized return")
    benchmark = _align(pd.read_parquet(raw_paths["benchmark"]), realized).fillna(0.0)
    universe = _align(pd.read_parquet(raw_paths["universe"]), realized).fillna(False).astype(bool)
    members = {
        name: normalize_weight(_align(pd.read_parquet(raw_paths[name]), realized), name)
        for name in MEMBER_NAMES
    }
    return ReportInputs(
        project_root=root,
        manifest=manifest,
        realized_return=realized,
        benchmark_weight=benchmark.astype("float64"),
        universe=universe,
        members=members,
        source_paths={name: raw_paths[name] for name in required},
        final_dir=root / "experiments/output/final_ensemble_rationale_2018_v3",
        price_cache=root / "outputs/cache/run_alpha_ensembles/price_alpha",
    )


def normalize_weight(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    partial = frame.isna().any(axis=1) & ~frame.isna().all(axis=1)
    if partial.any():
        raise ValueError(f"{label} has partial-row NaN: {frame.index[partial][0]}")
    all_nan = frame.isna().all(axis=1).to_numpy()
    valid = np.flatnonzero(~all_nan)
    if valid.size == 0 or all_nan[int(valid[0]) :].any():
        raise ValueError(f"{label} has invalid all-NaN dates")
    result = frame.fillna(0.0).astype("float64")
    if not np.isfinite(result.to_numpy()).all():
        raise ValueError(f"{label} has non-finite weights")
    return result


def _align(frame: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    return frame.reindex(index=reference.index, columns=reference.columns)


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("final_method_key") != FINAL_METHOD:
        raise ValueError("report final method differs from Qlib twin contract")
    members = tuple(row["member"] for row in manifest.get("members", ()))
    if members != MEMBER_NAMES:
        raise ValueError("report member order differs from the frozen 18-member contract")
    parameters = manifest.get("final_rationale_parameters", {})
    expected = {
        "history_lag_days": 1,
        "lookback_days": 63,
        "rebalance_interval_days": 21,
        "family_weight_cap": 0.6,
        "negative_screen_fraction": 0.1,
        "target_annual_alpha_volatility": 0.03,
        "maximum_embedded_multiplier": 1.0,
        "warmup_alpha_multiplier": 0.0,
        "enhanced_index_scalar_multiplier": 0.1,
    }
    for key, value in expected.items():
        if not np.isclose(float(parameters.get(key, np.nan)), value, atol=TOLERANCE):
            raise ValueError(f"report rationale parameter differs: {key}")
