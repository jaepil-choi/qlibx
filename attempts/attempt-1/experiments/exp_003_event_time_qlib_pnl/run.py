from __future__ import annotations

# ruff: noqa: E402, I001

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "outputs"
sys.path.insert(0, str(HERE))

from qlibx import Project
from qlibx.data import ConfigDrivenDataLoader, require_matrix_axes
from qlibx.execution import run_signed_execution

from strategy import signed_momentum

START = "2025-01-01"
END = "2025-03-31"
ACTIVE_BOOKSIZE = 1_000_000_000.0
INITIAL_CASH = 3_000_000_000.0
DATASETS = (
    "returns",
    "execution_price",
    "valuation_price",
    "execution_universe",
    "execution_observed",
    "execution_tradable",
    "execution_shortable",
    "execution_volume",
)
UPSTREAM = (
    "data/preprocessed/adjusted_prices.parquet",
    "data/preprocessed/k200_members.parquet",
    "data/preprocessed/sector_classification.parquet",
)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_pit_matrix(
    loader: ConfigDrivenDataLoader,
    name: str,
    *,
    tickers: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.Timedelta]:
    spec = loader.catalog.datasets[name]
    axes = require_matrix_axes(spec)
    # The whole window is loaded to build the backtest input; the point-in-time cut is
    # applied per decision inside the execution loop, not here.
    table = loader.load_full_history(
        name, reason="backtest input matrix", start=START, end=END, tickers=tickers
    )
    event_time = pd.to_datetime(table[spec.time_field], errors="raise")
    available_at = pd.to_datetime(table[spec.availability_field], errors="raise")
    violation = (available_at - event_time).max()
    matrix = table.pivot(index=axes.index, columns=axes.columns, values=axes.values)
    matrix = matrix.sort_index().sort_index(axis=1)
    if spec.dtype:
        matrix = matrix.astype(spec.dtype)
    return matrix, violation


def main() -> None:
    resolved_output = OUTPUT.resolve()
    if resolved_output.parent != HERE.resolve():
        raise RuntimeError("experiment output escaped its experiment directory")
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)

    before = {path: _digest(ROOT / path) for path in UPSTREAM}
    loader = ConfigDrivenDataLoader.from_project(Project.load(ROOT))
    loaded: dict[str, pd.DataFrame] = {}
    availability_violations: dict[str, pd.Timedelta] = {}
    for name in DATASETS:
        loaded[name], availability_violations[name] = _load_pit_matrix(loader, name)

    common_dates = loaded["returns"].index
    common_tickers = loaded["returns"].columns
    for matrix in loaded.values():
        common_dates = common_dates.intersection(matrix.index)
        common_tickers = common_tickers.intersection(matrix.columns)
    loaded = {
        name: matrix.reindex(index=common_dates, columns=common_tickers)
        for name, matrix in loaded.items()
    }

    complete = (
        loaded["execution_price"].gt(0).all(axis=0)
        & loaded["valuation_price"].gt(0).all(axis=0)
        & loaded["execution_volume"].ge(0).all(axis=0)
        & loaded["execution_observed"].fillna(False).all(axis=0)
    )
    selected = common_tickers[complete]
    if len(selected) < 20:
        raise RuntimeError(f"too few complete instruments for signed alpha: {len(selected)}")
    loaded = {name: matrix.loc[:, selected] for name, matrix in loaded.items()}

    universe = loaded["execution_universe"].fillna(False).astype(bool)
    tradable = loaded["execution_tradable"].fillna(False).astype(bool)
    shortable = loaded["execution_shortable"].fillna(False).astype(bool)
    alpha = signed_momentum(loaded["returns"], universe)
    result = run_signed_execution(
        signed_weights=alpha,
        execution_price=loaded["execution_price"].astype("float64"),
        valuation_price=loaded["valuation_price"].astype("float64"),
        universe=universe,
        observed=loaded["execution_observed"].fillna(False).astype(bool),
        tradable=tradable,
        shortable=shortable,
        volume=loaded["execution_volume"].astype("float64"),
        initial_cash=INITIAL_CASH,
        active_booksize=ACTIVE_BOOKSIZE,
        max_volume_participation=0.10,
        per_name_short_cap=0.023,
        safety_multiplier=1.10,
        inventory_retention="active_short_only",
        cost_policy={"stock": {"buy_rate": 0.0, "sell_rate": 0.0, "sell_tax": 0.0}},
    )
    after = {path: _digest(ROOT / path) for path in UPSTREAM}

    outputs = {
        "alpha": alpha,
        "orders": result.orders,
        "fills": result.fills,
        "signed_positions": result.signed_positions,
        "active_account": result.active_account,
        "composite_account": result.composite_account,
        "baseline_account": result.baseline_account,
        "capitalization_events": result.capitalization_events,
    }
    for name, frame in outputs.items():
        frame.to_parquet(OUTPUT / f"{name}.parquet")

    max_violation = max(availability_violations.values())
    sell_order_ids = set(
        result.orders.loc[result.orders["direction"].eq("sell"), "order_id"].tolist()
    )
    summary = {
        "status": "PASS",
        "execution_backend": result.evidence["execution_backend"],
        "qlib_version": result.evidence["qlib_version"],
        "catalog_fingerprint": loader.catalog.fingerprint,
        "dates": len(common_dates),
        "tickers": len(selected),
        "average_long_exposure": float(alpha.clip(lower=0).sum(axis=1).mean()),
        "average_short_exposure": float(-alpha.clip(upper=0).sum(axis=1).mean()),
        "negative_alpha_cells": int(alpha.lt(0).sum().sum()),
        "actual_sell_orders": int(result.orders["direction"].eq("sell").sum()),
        "actual_filled_sell_orders": int(
            result.fills.loc[result.fills["order_id"].isin(sell_order_ids), "filled_quantity"]
            .gt(0)
            .sum()
        ),
        "short_position_rows": int(result.signed_positions["held_quantity"].lt(0).sum()),
        "active_pnl": float(result.active_account.iloc[-1]["nav"] - ACTIVE_BOOKSIZE),
        "composite_shortfall": float(
            result.signed_positions["composite_quantity"].clip(upper=0).abs().max()
        ),
        "max_available_after_event_seconds": float(max_violation.total_seconds()),
        "upstream_hashes_unchanged": before == after,
        "information_adjustments": [],
        "compatibility_limitations": list(result.compatibility_limitations),
    }
    if (
        summary["execution_backend"] != "qlib"
        or summary["qlib_version"] != "0.9.7"
        or summary["negative_alpha_cells"] == 0
        or summary["actual_filled_sell_orders"] == 0
        or summary["short_position_rows"] == 0
        or summary["composite_shortfall"] > 1e-9
        or summary["max_available_after_event_seconds"] > 0
        or not summary["upstream_hashes_unchanged"]
    ):
        summary["status"] = "FAIL"
    (OUTPUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
