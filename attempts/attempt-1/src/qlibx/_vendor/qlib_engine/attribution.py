from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from .models import SignedAttributionResult
from .store import RunCatalog

ATTRIBUTION_ABSOLUTE_TOLERANCE = 1e-8
ATTRIBUTION_RELATIVE_TOLERANCE = 1e-12


def build_signed_attribution(
    catalog_path: str | Path,
    *,
    backtest_run_id: str,
) -> SignedAttributionResult:
    """저장된 signed run과 lineage만으로 realized active PnL을 분해합니다."""

    store = RunCatalog.open(catalog_path)
    backtest = store.get_run(backtest_run_id)
    if backtest.run_kind != "backtest":
        raise ValueError(f"attribution input is not a backtest run: {backtest_run_id}")
    backtest_config = backtest.metadata.get("backtest_config", {})
    if backtest_config.get("target_semantics") != "signed_weight":
        raise ValueError(f"attribution input is not a signed backtest: {backtest_run_id}")

    alpha_links = [
        link for link in store.get_parent_links(backtest_run_id) if link.role == "alpha_input"
    ]
    if len(alpha_links) != 1:
        raise ValueError("signed backtest must have exactly one alpha_input parent")
    alpha_run_id = alpha_links[0].run_id

    execution_price = _matrix(
        store.load_table(backtest_run_id, "execution_price"),
        "execution_price",
    )
    valuation_price = _matrix(
        store.load_table(backtest_run_id, "valuation_price"),
        "valuation_price",
    )
    if not valuation_price.index.equals(execution_price.index) or not (
        valuation_price.columns.equals(execution_price.columns)
    ):
        raise ValueError("stored execution_price and valuation_price axes differ")

    signed = store.load_table(backtest_run_id, "signed_positions").copy()
    required_signed = {
        "trade_date",
        "instrument_id",
        "intended_weight",
        "target_quantity",
        "held_quantity",
        "baseline_quantity",
        "composite_quantity",
    }
    missing_signed = required_signed.difference(signed.columns)
    if missing_signed:
        raise ValueError(f"signed_positions is missing columns: {sorted(missing_signed)}")
    signed["trade_date"] = pd.to_datetime(signed["trade_date"])
    signed["instrument_id"] = signed["instrument_id"].astype(str)
    if signed.duplicated(["trade_date", "instrument_id"]).any():
        raise ValueError("signed_positions primary key is duplicated")

    held = _pivot_signed(signed, "held_quantity", execution_price)
    prior_held = held.shift(1, fill_value=0.0)
    prior_valuation = valuation_price.shift(1)
    overnight_pnl = (prior_held * (execution_price - prior_valuation)).fillna(0.0)
    intraday_pnl = held * (valuation_price - execution_price)

    fills = store.load_table(backtest_run_id, "fills").copy()
    execution_cost = pd.DataFrame(
        0.0,
        index=execution_price.index,
        columns=execution_price.columns,
    )
    if not fills.empty:
        required_fills = {"trade_date", "instrument_id", "trade_cost"}
        missing_fills = required_fills.difference(fills.columns)
        if missing_fills:
            raise ValueError(f"fills is missing columns: {sorted(missing_fills)}")
        fills["trade_date"] = pd.to_datetime(fills["trade_date"])
        fills["instrument_id"] = fills["instrument_id"].astype(str)
        grouped_cost = fills.groupby(["trade_date", "instrument_id"], sort=False)[
            "trade_cost"
        ].sum()
        execution_cost = (
            grouped_cost.unstack()
            .reindex(
                index=execution_price.index,
                columns=execution_price.columns,
                fill_value=0.0,
            )
            .fillna(0.0)
        )

    gross_pnl = overnight_pnl + intraday_pnl
    net_pnl = gross_pnl - execution_cost
    instrument_daily = _instrument_table(
        signed=signed,
        execution_price=execution_price,
        valuation_price=valuation_price,
        prior_held=prior_held,
        overnight_pnl=overnight_pnl,
        intraday_pnl=intraday_pnl,
        execution_cost=execution_cost,
        net_pnl=net_pnl,
        benchmark_weight=_optional_matrix(
            store,
            backtest_run_id,
            "benchmark_weight",
            execution_price,
        ),
    )

    active_account = store.load_table(backtest_run_id, "active_account_daily").copy()
    required_account = {"trade_date", "money_pnl"}
    missing_account = required_account.difference(active_account.columns)
    if missing_account:
        raise ValueError(f"active_account_daily is missing columns: {sorted(missing_account)}")
    active_account["trade_date"] = pd.to_datetime(active_account["trade_date"])
    active_money_pnl = active_account.set_index("trade_date")["money_pnl"].reindex(
        execution_price.index
    )
    if active_money_pnl.isna().any():
        raise ValueError("active_account_daily does not cover execution calendar")

    long_pnl = overnight_pnl.where(prior_held.gt(0.0), 0.0).sum(axis=1)
    long_pnl += intraday_pnl.where(held.gt(0.0), 0.0).sum(axis=1)
    short_pnl = overnight_pnl.where(prior_held.lt(0.0), 0.0).sum(axis=1)
    short_pnl += intraday_pnl.where(held.lt(0.0), 0.0).sum(axis=1)
    total_execution_cost = execution_cost.sum(axis=1)
    total_net_pnl = net_pnl.sum(axis=1)
    summary_daily = pd.DataFrame(
        {
            "trade_date": execution_price.index,
            "long_pnl": long_pnl.to_numpy(),
            "short_pnl": short_pnl.to_numpy(),
            "gross_pnl": gross_pnl.sum(axis=1).to_numpy(),
            "execution_cost": total_execution_cost.to_numpy(),
            "net_pnl": total_net_pnl.to_numpy(),
            "active_money_pnl": active_money_pnl.to_numpy(),
        }
    )
    summary_daily["reconciliation_error"] = (
        summary_daily["net_pnl"] - summary_daily["active_money_pnl"]
    )
    scale = max(
        1.0,
        float(summary_daily["active_money_pnl"].abs().max()),
    )
    tolerance = max(
        ATTRIBUTION_ABSOLUTE_TOLERANCE,
        scale * ATTRIBUTION_RELATIVE_TOLERANCE,
    )
    if float(summary_daily["reconciliation_error"].abs().max()) > tolerance:
        raise ValueError(
            "stored signed attribution does not reconcile active money PnL: "
            f"max_error={summary_daily['reconciliation_error'].abs().max()}, "
            f"tolerance={tolerance}"
        )

    member_daily = _member_attribution(
        store=store,
        alpha_run_id=alpha_run_id,
        execution_price=execution_price,
        signal_lag=int(backtest_config.get("signal_lag", 1)),
        held=held,
        prior_held=prior_held,
        overnight_pnl=overnight_pnl,
        intraday_pnl=intraday_pnl,
        execution_cost=execution_cost,
    )
    return SignedAttributionResult(
        backtest_run_id=backtest_run_id,
        alpha_run_id=alpha_run_id,
        instrument_daily=instrument_daily,
        member_daily=member_daily,
        summary_daily=summary_daily,
    )


def _member_attribution(
    *,
    store: RunCatalog,
    alpha_run_id: str,
    execution_price: pd.DataFrame,
    signal_lag: int,
    held: pd.DataFrame,
    prior_held: pd.DataFrame,
    overnight_pnl: pd.DataFrame,
    intraday_pnl: pd.DataFrame,
    execution_cost: pd.DataFrame,
) -> pd.DataFrame:
    member_links = [link for link in store.get_parent_links(alpha_run_id) if link.role == "member"]
    if member_links:
        if any(link.weight is None for link in member_links):
            raise ValueError("ensemble member lineage is missing weights")
        members = {link.run_id: float(link.weight) for link in member_links}
    else:
        members = {alpha_run_id: 1.0}
    if not np.isclose(sum(members.values()), 1.0):
        raise ValueError("stored ensemble member weights must sum to 1")

    weighted: dict[str, pd.DataFrame] = {}
    for member_run_id, weight in members.items():
        alpha = _matrix(store.load_alpha(member_run_id), f"alpha:{member_run_id}")
        if not alpha.index.equals(execution_price.index) or not (
            alpha.columns.equals(execution_price.columns)
        ):
            raise ValueError(f"member alpha axes differ: {member_run_id}")
        weighted[member_run_id] = alpha.shift(signal_lag, fill_value=0.0).astype("float64") * weight
    combined = sum(weighted.values())
    nonzero = combined.abs().gt(1e-12)
    ratios = {
        member_run_id: values.div(combined.where(nonzero)).ffill().fillna(0.0)
        for member_run_id, values in weighted.items()
    }
    ratio_sum = sum(ratios.values())
    owned = held.ne(0.0) | prior_held.ne(0.0)
    unresolved = owned & ~np.isclose(ratio_sum, 1.0, atol=1e-10, rtol=1e-12)
    if unresolved.any().any():
        date, instrument = unresolved.stack().loc[lambda values: values].index[0]
        raise ValueError(
            "stored member lineage cannot explain realized signed position: "
            f"date={date}, instrument={instrument}"
        )

    rows: list[dict[str, object]] = []
    for member_run_id in sorted(members):
        current_ratio = ratios[member_run_id]
        prior_ratio = current_ratio.shift(1).fillna(0.0)
        member_overnight = overnight_pnl * prior_ratio
        member_intraday = intraday_pnl * current_ratio
        member_cost = execution_cost * current_ratio
        member_gross = member_overnight + member_intraday
        member_net = member_gross - member_cost
        for date in execution_price.index:
            rows.append(
                {
                    "trade_date": pd.Timestamp(date),
                    "member_alpha_run_id": member_run_id,
                    "member_weight": members[member_run_id],
                    "overnight_pnl": float(member_overnight.loc[date].sum()),
                    "intraday_pnl": float(member_intraday.loc[date].sum()),
                    "gross_pnl": float(member_gross.loc[date].sum()),
                    "execution_cost": float(member_cost.loc[date].sum()),
                    "net_pnl": float(member_net.loc[date].sum()),
                }
            )
    member_daily = pd.DataFrame(rows)
    allocated = member_daily.groupby("trade_date")["net_pnl"].sum().reindex(execution_price.index)
    expected = (overnight_pnl + intraday_pnl - execution_cost).sum(axis=1)
    if not np.allclose(
        allocated.to_numpy(),
        expected.to_numpy(),
        atol=ATTRIBUTION_ABSOLUTE_TOLERANCE,
        rtol=ATTRIBUTION_RELATIVE_TOLERANCE,
    ):
        raise ValueError("stored member attribution does not sum to active attribution")
    return member_daily


def _instrument_table(
    *,
    signed: pd.DataFrame,
    execution_price: pd.DataFrame,
    valuation_price: pd.DataFrame,
    prior_held: pd.DataFrame,
    overnight_pnl: pd.DataFrame,
    intraday_pnl: pd.DataFrame,
    execution_cost: pd.DataFrame,
    net_pnl: pd.DataFrame,
    benchmark_weight: pd.DataFrame,
) -> pd.DataFrame:
    table = signed.sort_values(["trade_date", "instrument_id"]).reset_index(drop=True)
    keyed = table.set_index(["trade_date", "instrument_id"])
    values: Mapping[str, pd.DataFrame] = {
        "execution_price": execution_price,
        "valuation_price": valuation_price,
        "prior_held_quantity": prior_held,
        "overnight_pnl": overnight_pnl,
        "intraday_pnl": intraday_pnl,
        "gross_pnl": overnight_pnl + intraday_pnl,
        "execution_cost": execution_cost,
        "net_pnl": net_pnl,
        "benchmark_weight": benchmark_weight,
    }
    for name, matrix in values.items():
        stacked = matrix.rename_axis(index="trade_date", columns="instrument_id").stack(
            future_stack=True
        )
        keyed[name] = stacked.reindex(keyed.index).astype("float64")
    if keyed[list(values)].isna().any().any():
        raise ValueError("stored signed attribution axes do not cover signed positions")
    return keyed.reset_index()


def _pivot_signed(
    signed: pd.DataFrame,
    value: str,
    like: pd.DataFrame,
) -> pd.DataFrame:
    matrix = signed.pivot(
        index="trade_date",
        columns="instrument_id",
        values=value,
    )
    return matrix.reindex(index=like.index, columns=like.columns).astype("float64")


def _matrix(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{name} must be a pandas DataFrame")
    matrix = frame.copy()
    matrix.index = pd.DatetimeIndex(matrix.index)
    matrix.columns = pd.Index(matrix.columns.astype(str), name=matrix.columns.name)
    if matrix.index.has_duplicates or matrix.columns.has_duplicates:
        raise ValueError(f"{name} axes must be unique")
    return matrix.astype("float64")


def _optional_matrix(
    store: RunCatalog,
    run_id: str,
    name: str,
    like: pd.DataFrame,
) -> pd.DataFrame:
    try:
        matrix = _matrix(store.load_table(run_id, name), name)
    except KeyError:
        return pd.DataFrame(0.0, index=like.index, columns=like.columns)
    if not matrix.index.equals(like.index) or not matrix.columns.equals(like.columns):
        raise ValueError(f"stored {name} axes differ from execution_price")
    return matrix
