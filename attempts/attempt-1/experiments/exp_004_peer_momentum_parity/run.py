"""Compare integration-codex peer momentum with an independent qlibx StrategyAgent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from strategy import build_qlibx_alpha

from qlibx.execution import open_run_catalog, run_signed_execution

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = EXPERIMENT_DIR / "outputs"
REFERENCE_DIR = ROOT / "references" / "qlib-integration-codex" / "outputs" / "signed_peer_momentum"

VALUE_COLUMNS = {
    "returns": "return",
    "peer_groups": "peer_group",
    "universe": "in_universe",
    "observed": "observed",
    "tradable": "tradable",
    "shortable": "shortable",
    "execution_price": "execution_price",
    "valuation_price": "valuation_price",
    "position_unit_factor": "position_unit_factor",
    "volume": "volume",
}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    reference_summary = json.loads((REFERENCE_DIR / "summary.json").read_text(encoding="utf-8"))
    catalog = open_run_catalog(REFERENCE_DIR / "runs.duckdb")
    reference_alpha = catalog.load_alpha(reference_summary["alpha_run_id"])
    reference_alpha.index = pd.DatetimeIndex(reference_alpha.index)
    reference_alpha.columns = reference_alpha.columns.astype(str)

    matrices = {
        name: _load_matrix(REFERENCE_DIR / "project-data" / f"{name}.parquet", value)
        for name, value in VALUE_COLUMNS.items()
    }
    dates = matrices["returns"].index
    tickers = matrices["returns"].columns
    matrices = {
        name: frame.reindex(index=dates, columns=tickers) for name, frame in matrices.items()
    }
    for name in ("universe", "observed", "tradable", "shortable"):
        matrices[name] = matrices[name].astype(bool)
    reference_alpha = reference_alpha.reindex(index=dates, columns=tickers).astype("float64")

    qlibx_alpha, audit = build_qlibx_alpha(
        matrices["returns"],
        matrices["peer_groups"],
        matrices["universe"],
    )
    alpha_comparison = _compare_alpha(reference_alpha, qlibx_alpha)
    qlibx_alpha.to_parquet(OUTPUT_DIR / "qlibx-alpha.parquet")
    audit.to_parquet(OUTPUT_DIR / "decision-audit.parquet", index=False)

    execution_kwargs = {
        "execution_price": matrices["execution_price"].astype("float64"),
        "valuation_price": matrices["valuation_price"].astype("float64"),
        "universe": matrices["universe"],
        "observed": matrices["observed"],
        "tradable": matrices["tradable"],
        "shortable": matrices["shortable"],
        "volume": matrices["volume"].astype("float64"),
        "initial_cash": 3_000_000_000.0,
        "active_booksize": 1_000_000_000.0,
        "cost_policy": {"stock": {"buy_rate": 0.0, "sell_rate": 0.0, "sell_tax": 0.0}},
        "max_volume_participation": 0.10,
        "per_name_short_cap": 0.06,
        "safety_multiplier": 1.10,
        "inventory_retention": "active_short_only",
    }
    factor = matrices["position_unit_factor"].astype("float64")
    factor_contract_error = None
    try:
        run_signed_execution(
            signed_weights=reference_alpha,
            position_unit_factor=factor,
            **execution_kwargs,
        )
    except ValueError as error:
        factor_contract_error = str(error)
    if factor_contract_error is None:
        raise RuntimeError("qlibx unexpectedly accepted a non-unit position adjustment factor")
    baseline_execution = run_signed_execution(
        signed_weights=reference_alpha,
        **execution_kwargs,
    )
    qlibx_execution = run_signed_execution(
        signed_weights=qlibx_alpha,
        **execution_kwargs,
    )

    reference_run_id = reference_summary["backtest_run_id"]
    reference_tables = {
        "orders": catalog.load_table(reference_run_id, "orders"),
        "fills": catalog.load_table(reference_run_id, "fills"),
        "signed_positions": catalog.load_table(reference_run_id, "signed_positions"),
        "composite_account": catalog.load_table(reference_run_id, "account_daily"),
        "baseline_account": catalog.load_table(reference_run_id, "baseline_account_daily"),
        "active_account": catalog.load_table(reference_run_id, "active_account_daily"),
    }
    baseline_tables = _execution_tables(baseline_execution)
    qlibx_tables = _execution_tables(qlibx_execution)
    sort_keys = {
        "orders": ["trade_date", "order_id"],
        "fills": ["trade_date", "fill_id"],
        "signed_positions": ["trade_date", "instrument_id"],
        "composite_account": ["trade_date"],
        "baseline_account": ["trade_date"],
        "active_account": ["trade_date"],
    }
    execution_engine_comparison = {
        name: _compare_table(reference_tables[name], baseline_tables[name], sort_keys[name])
        for name in reference_tables
    }
    end_to_end_comparison = {
        name: _compare_table(reference_tables[name], qlibx_tables[name], sort_keys[name])
        for name in reference_tables
    }

    for name, table in qlibx_tables.items():
        _normalize_table(table, sort_keys[name]).to_parquet(
            OUTPUT_DIR / f"qlibx-{name.replace('_', '-')}.parquet",
            index=False,
        )

    final_reference_pnl = float(
        reference_tables["active_account"].iloc[-1]["nav"] - 1_000_000_000.0
    )
    final_baseline_pnl = float(_last_nav(baseline_tables["active_account"]) - 1_000_000_000.0)
    final_qlibx_pnl = float(_last_nav(qlibx_tables["active_account"]) - 1_000_000_000.0)
    alpha_exact = bool(alpha_comparison["exact_equal"])
    engine_bit_exact = all(
        item["value_exact_equal"] for item in execution_engine_comparison.values()
    )
    engine_equivalent = all(
        item["equivalent_at_1e_8"] for item in execution_engine_comparison.values()
    )
    end_to_end_bit_exact = alpha_exact and all(
        item["value_exact_equal"] for item in end_to_end_comparison.values()
    )
    end_to_end_equivalent = alpha_exact and all(
        item["equivalent_at_1e_8"] for item in end_to_end_comparison.values()
    )
    same_result = end_to_end_equivalent and final_qlibx_pnl == final_reference_pnl
    summary = {
        "result": "PASS_WITH_FLOAT_TOLERANCE" if same_result else "DIFFERENT",
        "same_result": same_result,
        "bit_exact_end_to_end": end_to_end_bit_exact,
        "reference": {
            "alpha_run_id": reference_summary["alpha_run_id"],
            "backtest_run_id": reference_run_id,
            "trading_days": len(dates),
            "ticker_count": len(tickers),
            "final_active_pnl": final_reference_pnl,
        },
        "qlibx_strategy_contract": {
            "strategy_id": "peer_momentum.ew_decay.top_kpct.long_short.qlibx",
            "decision_count": len(audit),
            "unique_invocation_count": int(audit["invocation_id"].nunique()),
            "unique_result_count": int(audit["result_id"].nunique()),
        },
        "alpha_comparison": alpha_comparison,
        "execution_engine_isolation": {
            "description": "stored integration-codex alpha executed by public qlibx",
            "all_table_values_exact": engine_bit_exact,
            "all_table_values_equivalent_at_1e_8": engine_equivalent,
            "reference_final_active_pnl": final_reference_pnl,
            "qlibx_final_active_pnl": final_baseline_pnl,
            "pnl_difference": final_baseline_pnl - final_reference_pnl,
            "tables": execution_engine_comparison,
        },
        "end_to_end": {
            "description": "qlibx StrategyAgent alpha executed by public qlibx",
            "all_table_values_exact": end_to_end_bit_exact,
            "all_table_values_equivalent_at_1e_8": end_to_end_equivalent,
            "reference_final_active_pnl": final_reference_pnl,
            "qlibx_final_active_pnl": final_qlibx_pnl,
            "pnl_difference": final_qlibx_pnl - final_reference_pnl,
            "tables": end_to_end_comparison,
        },
        "conditions": {
            "signal": "previous-bar leave-one-out equal-weight peer return",
            "decay": "five-step sparse linear decay",
            "selection": "absolute top 5 percent, keeping ties",
            "long_exposure": 0.25,
            "short_exposure": 0.25,
            "max_abs_weight": 0.05,
            "initial_cash": 3_000_000_000.0,
            "active_booksize": 1_000_000_000.0,
            "transaction_cost": 0.0,
            "max_volume_participation": 0.10,
            "per_name_short_cap": 0.06,
            "safety_multiplier": 1.10,
            "inventory_retention": "active_short_only",
        },
        "data_contract_difference": {
            "reference_used_position_unit_factor": True,
            "non_unit_factor_cell_count": int(factor.ne(1.0).sum().sum()),
            "factor_minimum": float(factor.min().min()),
            "factor_maximum": float(factor.max().max()),
            "qlibx_exact_input_rejection": factor_contract_error,
            "qlibx_execution_used_factor": False,
        },
        "limitations": [
            (
                "The historical reference strategy module is not re-imported because its former "
                "private package is absent; the completed run catalog and saved project-data "
                "matrices are the baseline."
            ),
            (
                "Both executions use qlibx's matched-capitalization compatibility path, not "
                "native short accounting in Qlib."
            ),
            (
                "The reference execution supplied a position adjustment factor. qlibx "
                "deliberately rejects that input and was run with unit factors, so execution "
                "parity is a policy comparison rather than identical execution inputs."
            ),
        ],
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))


def _load_matrix(path: Path, value_column: str) -> pd.DataFrame:
    table = pd.read_parquet(path)
    table["date"] = pd.to_datetime(table["date"])
    table["ticker"] = table["ticker"].astype(str)
    matrix = table.pivot(index="date", columns="ticker", values=value_column)
    matrix.index = pd.DatetimeIndex(matrix.index)
    return matrix


def _compare_alpha(reference: pd.DataFrame, candidate: pd.DataFrame) -> dict[str, Any]:
    difference = candidate - reference
    absolute = difference.abs()
    divergent = absolute.stack(future_stack=True)
    divergent = divergent[divergent.gt(0.0)]
    tolerance_divergent = absolute.stack(future_stack=True)
    tolerance_divergent = tolerance_divergent[tolerance_divergent.gt(1e-12)]
    reference_selected = reference.ne(0.0)
    candidate_selected = candidate.ne(0.0)
    first = None
    if not divergent.empty:
        date, ticker = divergent.index[0]
        first = {
            "trade_date": pd.Timestamp(date),
            "ticker": str(ticker),
            "reference_weight": float(reference.loc[date, ticker]),
            "qlibx_weight": float(candidate.loc[date, ticker]),
            "difference": float(difference.loc[date, ticker]),
        }
    return {
        "exact_equal": bool(reference.equals(candidate)),
        "allclose_at_1e_12": bool(np.allclose(reference, candidate, atol=1e-12, rtol=0.0)),
        "max_abs_weight_difference": float(absolute.max().max()),
        "exactly_different_cell_count": len(divergent),
        "different_cell_count_at_1e_12": len(tolerance_divergent),
        "selection_mismatch_cell_count": int(reference_selected.ne(candidate_selected).sum().sum()),
        "selection_agreement_rate": float(
            reference_selected.eq(candidate_selected).sum().sum() / reference.size
        ),
        "first_exact_divergence": first,
        "reference_average_long_exposure": float(reference.clip(lower=0.0).sum(axis=1).mean()),
        "qlibx_average_long_exposure": float(candidate.clip(lower=0.0).sum(axis=1).mean()),
        "reference_average_short_exposure": float(-reference.clip(upper=0.0).sum(axis=1).mean()),
        "qlibx_average_short_exposure": float(-candidate.clip(upper=0.0).sum(axis=1).mean()),
    }


def _execution_tables(result: Any) -> dict[str, pd.DataFrame]:
    return {
        "orders": result.orders,
        "fills": result.fills,
        "signed_positions": result.signed_positions,
        "composite_account": result.composite_account,
        "baseline_account": result.baseline_account,
        "active_account": result.active_account,
    }


def _normalize_table(table: pd.DataFrame, sort_by: list[str]) -> pd.DataFrame:
    result = table.copy()
    if not isinstance(result.index, pd.RangeIndex):
        index_name = result.index.name or "index"
        if index_name not in result.columns:
            result = result.reset_index()
    for column in result.columns:
        if column.endswith("date"):
            result[column] = pd.to_datetime(result[column])
    keys = [column for column in sort_by if column in result.columns]
    if keys:
        result = result.sort_values(keys, kind="stable")
    return result.reset_index(drop=True)


def _compare_table(
    reference: pd.DataFrame,
    candidate: pd.DataFrame,
    sort_by: list[str],
) -> dict[str, Any]:
    left = _normalize_table(reference, sort_by)
    right = _normalize_table(candidate, sort_by)
    missing = [column for column in left.columns if column not in right.columns]
    extra = [column for column in right.columns if column not in left.columns]
    common = [column for column in left.columns if column in right.columns]
    same_shape = left.shape == right.shape
    value_exact = False
    equivalent = False
    max_numeric_difference = None
    mismatch_count = None
    mismatch_columns: dict[str, dict[str, Any]] = {}
    first_difference = None
    if len(left) == len(right) and not missing and not extra:
        right = right[left.columns]
        equal = left.eq(right) | (left.isna() & right.isna())
        value_exact = bool(equal.all().all())
        mismatch_count = int((~equal).sum().sum())
        numeric_columns = [
            column
            for column in left.columns
            if pd.api.types.is_numeric_dtype(left[column])
            and pd.api.types.is_numeric_dtype(right[column])
        ]
        if numeric_columns:
            max_numeric_difference = float(
                (left[numeric_columns].astype("float64") - right[numeric_columns].astype("float64"))
                .abs()
                .max()
                .max()
            )
        equivalent_by_column = []
        for column in left.columns:
            if column in numeric_columns:
                close = np.isclose(
                    left[column].astype("float64"),
                    right[column].astype("float64"),
                    atol=1e-8,
                    rtol=0.0,
                    equal_nan=True,
                )
                equivalent_by_column.append(bool(close.all()))
            else:
                equivalent_by_column.append(bool(equal[column].all()))
            if not equal[column].all():
                details: dict[str, Any] = {"exact_mismatch_count": int((~equal[column]).sum())}
                if column in numeric_columns:
                    details["max_abs_difference"] = float(
                        (left[column].astype("float64") - right[column].astype("float64"))
                        .abs()
                        .max()
                    )
                mismatch_columns[str(column)] = details
        equivalent = all(equivalent_by_column)
        if not value_exact:
            row, column_position = np.argwhere((~equal).to_numpy())[0]
            column = left.columns[column_position]
            first_difference = {
                "row": int(row),
                "column": str(column),
                "reference": left.iloc[row, column_position],
                "qlibx": right.iloc[row, column_position],
            }
    return {
        "reference_rows": len(left),
        "qlibx_rows": len(right),
        "same_shape": same_shape,
        "missing_columns": missing,
        "extra_columns": extra,
        "value_exact_equal": value_exact,
        "equivalent_at_1e_8": equivalent,
        "mismatch_cell_count": mismatch_count,
        "mismatch_columns": mismatch_columns,
        "max_abs_numeric_difference": max_numeric_difference,
        "first_difference": first_difference,
        "common_column_count": len(common),
    }


def _last_nav(table: pd.DataFrame) -> float:
    normalized = _normalize_table(table, ["trade_date"])
    return float(normalized.iloc[-1]["nav"])


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return str(value)


if __name__ == "__main__":
    main()
