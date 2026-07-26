from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .models import EnhancedIndexAttributionResult
from .store import RunCatalog


def build_enhanced_index_attribution(
    catalog_path: str | Path,
    *,
    backtest_run_id: str,
) -> EnhancedIndexAttributionResult:
    """Stored member intent와 optimizer/Qlib artifact의 lineage를 재구성합니다."""

    store = RunCatalog.open(catalog_path)
    backtest = store.get_run(backtest_run_id)
    if backtest.run_kind != "backtest":
        raise ValueError(
            f"enhanced attribution input is not a backtest: {backtest_run_id}"
        )
    config = backtest.metadata.get("backtest_config", {})
    if config.get("target_semantics") != "enhanced_index":
        raise ValueError(
            f"attribution input is not an enhanced-index backtest: {backtest_run_id}"
        )
    alpha_links = [
        link
        for link in store.get_parent_links(backtest_run_id)
        if link.role == "alpha_input"
    ]
    if len(alpha_links) != 1:
        raise ValueError(
            "enhanced-index backtest must have exactly one alpha_input parent"
        )
    alpha_run_id = alpha_links[0].run_id
    desired = _matrix(
        store.load_table(backtest_run_id, "desired_active_exposure"),
        "desired_active_exposure",
    )
    member_intent = _member_intent(
        store,
        alpha_run_id=alpha_run_id,
        desired=desired,
        signal_lag=int(config.get("signal_lag", 1)),
    )

    constituent = store.load_table(
        backtest_run_id, "optimizer_constituent_daily"
    ).copy()
    physical = store.load_table(
        backtest_run_id, "optimizer_physical_daily"
    ).copy()
    required_constituent = {
        "trade_date",
        "constituent_id",
        "benchmark_weight",
        "desired_active_exposure",
        "desired_total_exposure",
        "realized_lookthrough_exposure",
    }
    required_physical = {
        "trade_date",
        "instrument_id",
        "target_physical_weight",
    }
    if missing := required_constituent.difference(constituent.columns):
        raise ValueError(
            f"optimizer constituent artifact is missing: {sorted(missing)}"
        )
    if missing := required_physical.difference(physical.columns):
        raise ValueError(
            f"optimizer physical artifact is missing: {sorted(missing)}"
        )
    constituent["trade_date"] = pd.to_datetime(constituent["trade_date"])
    physical["trade_date"] = pd.to_datetime(physical["trade_date"])
    constituent["constituent_id"] = constituent["constituent_id"].astype(str)
    physical["instrument_id"] = physical["instrument_id"].astype(str)
    _validate_primary_key(
        constituent, ["trade_date", "constituent_id"], "optimizer constituent"
    )
    _validate_primary_key(
        physical, ["trade_date", "instrument_id"], "optimizer physical"
    )

    lookthrough = _matrix(
        store.load_table(backtest_run_id, "lookthrough_matrix"),
        "lookthrough_matrix",
        datetime_index=False,
    )
    target = _matrix(
        store.load_table(backtest_run_id, "target_weights"),
        "target_weights",
    )
    expected_lookthrough = target @ lookthrough.T
    realized_lookthrough = constituent.pivot(
        index="trade_date",
        columns="constituent_id",
        values="realized_lookthrough_exposure",
    ).reindex(
        index=expected_lookthrough.index,
        columns=expected_lookthrough.columns,
    )
    if not np.allclose(
        expected_lookthrough.to_numpy(),
        realized_lookthrough.to_numpy(),
        atol=1e-8,
        rtol=1e-12,
    ):
        raise ValueError(
            "stored optimizer look-through does not match physical target exactly once"
        )
    stored_desired = constituent.pivot(
        index="trade_date",
        columns="constituent_id",
        values="desired_active_exposure",
    ).reindex(index=desired.index, columns=desired.columns)
    if not np.allclose(
        stored_desired.to_numpy(),
        desired.to_numpy(),
        atol=1e-12,
        rtol=1e-12,
    ):
        raise ValueError(
            "stored optimizer desired active exposure differs from alpha artifact"
        )

    held = _held_quantity(
        store.load_table(backtest_run_id, "positions"),
        index=target.index,
        columns=target.columns,
    )
    target_long = target.rename_axis(
        index="trade_date", columns="instrument_id"
    ).stack(future_stack=True).rename("stored_target_weight").reset_index()
    held_long = held.rename_axis(
        index="trade_date", columns="instrument_id"
    ).stack(future_stack=True).rename("held_quantity").reset_index()
    physical = physical.merge(
        target_long,
        on=["trade_date", "instrument_id"],
        how="left",
        validate="one_to_one",
    ).merge(
        held_long,
        on=["trade_date", "instrument_id"],
        how="left",
        validate="one_to_one",
    )
    if physical[["stored_target_weight", "held_quantity"]].isna().any().any():
        raise ValueError("stored physical attribution axes are incomplete")
    if not np.allclose(
        physical["target_physical_weight"],
        physical["stored_target_weight"],
        atol=1e-12,
        rtol=1e-12,
    ):
        raise ValueError(
            "stored optimizer physical target differs from execution target artifact"
        )
    return EnhancedIndexAttributionResult(
        backtest_run_id=backtest_run_id,
        alpha_run_id=alpha_run_id,
        member_intent_daily=member_intent,
        constituent_daily=constituent.sort_values(
            ["trade_date", "constituent_id"]
        ).reset_index(drop=True),
        physical_daily=physical.sort_values(
            ["trade_date", "instrument_id"]
        ).reset_index(drop=True),
    )


def _member_intent(
    store: RunCatalog,
    *,
    alpha_run_id: str,
    desired: pd.DataFrame,
    signal_lag: int,
) -> pd.DataFrame:
    links = [
        link for link in store.get_parent_links(alpha_run_id) if link.role == "member"
    ]
    if links:
        if any(link.weight is None for link in links):
            raise ValueError("enhanced-index member lineage is missing weights")
        members = {link.run_id: float(link.weight) for link in links}
    else:
        members = {alpha_run_id: 1.0}
    if not np.isclose(sum(members.values()), 1.0):
        raise ValueError("enhanced-index member weights must sum to 1")
    rows: list[pd.DataFrame] = []
    combined = pd.DataFrame(0.0, index=desired.index, columns=desired.columns)
    for member_run_id in sorted(members):
        alpha = _matrix(store.load_alpha(member_run_id), member_run_id)
        if not alpha.index.equals(desired.index) or not alpha.columns.equals(
            desired.columns
        ):
            raise ValueError(
                f"enhanced-index member alpha axes differ: {member_run_id}"
            )
        weighted = alpha.shift(signal_lag, fill_value=0.0) * members[member_run_id]
        combined = combined + weighted
        long = weighted.rename_axis(
            index="trade_date", columns="constituent_id"
        ).stack(future_stack=True).rename("weighted_active_exposure").reset_index()
        long["member_alpha_run_id"] = member_run_id
        long["member_weight"] = members[member_run_id]
        rows.append(long)
    if not np.allclose(
        combined.to_numpy(),
        desired.to_numpy(),
        atol=1e-12,
        rtol=1e-12,
    ):
        raise ValueError(
            "stored member alpha lineage does not sum to desired active exposure"
        )
    return pd.concat(rows, ignore_index=True).loc[
        :,
        [
            "trade_date",
            "member_alpha_run_id",
            "member_weight",
            "constituent_id",
            "weighted_active_exposure",
        ],
    ]


def _held_quantity(
    positions: pd.DataFrame,
    *,
    index: pd.DatetimeIndex,
    columns: pd.Index,
) -> pd.DataFrame:
    if positions.empty:
        return pd.DataFrame(0.0, index=index, columns=columns)
    required = {"trade_date", "instrument_id", "held_quantity"}
    if missing := required.difference(positions.columns):
        raise ValueError(f"positions artifact is missing: {sorted(missing)}")
    table = positions.copy()
    table["trade_date"] = pd.to_datetime(table["trade_date"])
    table["instrument_id"] = table["instrument_id"].astype(str)
    _validate_primary_key(table, ["trade_date", "instrument_id"], "positions")
    return table.pivot(
        index="trade_date",
        columns="instrument_id",
        values="held_quantity",
    ).reindex(index=index, columns=columns, fill_value=0.0).fillna(0.0)


def _validate_primary_key(
    table: pd.DataFrame,
    columns: list[str],
    name: str,
) -> None:
    if table.duplicated(columns).any():
        raise ValueError(f"{name} primary key is duplicated")


def _matrix(
    frame: pd.DataFrame,
    name: str,
    *,
    datetime_index: bool = True,
) -> pd.DataFrame:
    matrix = frame.copy()
    if datetime_index:
        matrix.index = pd.DatetimeIndex(matrix.index)
    else:
        matrix.index = pd.Index(matrix.index.astype(str))
    matrix.columns = pd.Index(matrix.columns.astype(str))
    if matrix.index.has_duplicates or matrix.columns.has_duplicates:
        raise ValueError(f"{name} axes must be unique")
    matrix = matrix.astype("float64")
    if not np.isfinite(matrix.to_numpy()).all():
        raise ValueError(f"{name} must contain finite values")
    return matrix
