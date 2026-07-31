"""
Carry indicator shared utilities (Gate 1C WS2 B2.2)
====================================================

Shared helpers for the five carry indicators in this package.

Per the Q50 verification spike (qorka 2026-05-14 / verification_spike_findings.md),
settlement is a time-varying daily quantity that lives in the OHLCV row,
NOT in ``ContractSpec`` metadata. Carry indicators consume ``df['settlement']``
at compute time. This module's :func:`extract_settlement` is the single
funnel for that access — keeps the column-name "settlement" centralized
so a future schema rename only touches one file.

NO_ERROR_HANDLING: per qorka quant-engine policy, missing columns raise
IND-005 via :func:`echolon.indicators.calculators._utils._require_columns`.
"""
from __future__ import annotations

import pandas as pd

from echolon.indicators.calculators._utils import _require_columns


# Standard rolling-window length for vol normalization in
# ``risk_adj_carry`` and other future carry-derived indicators. Trading
# days — 20 trading days ≈ 1 calendar month. Per qorka
# ``paradigms/carry/indicator_pool.py::CARRY_POOL_METADATA``.
DEFAULT_VOL_WINDOW: int = 20

# Rolling z-score window for ``carry_z_3m``. 63 trading days ≈ 3
# calendar months.
DEFAULT_Z_WINDOW: int = 63

# Lag in trading days for ``carry_change_20d``.
DEFAULT_CHANGE_LAG: int = 20

# Number of near contracts the curve-slope regression uses by default.
# Aligns with the qorka pool metadata "slope fit over 3 active contracts".
DEFAULT_SLOPE_N: int = 3


def extract_settlement(bar_row: pd.Series) -> float:
    """Extract the settlement price from an OHLCV row.

    Per Q50 spike: settlement lives in the per-contract OHLCV row as a
    distinct column from ``close``. Both are present (and differ) in
    SHFE data — close = last-trade-price, settlement = exchange-published
    daily mark used for margin/P&L.

    Args:
        bar_row: A single row of per-contract OHLCV (a pd.Series whose
            index includes the standard FUTURES_COLUMNS — see
            ``echolon.data.schemas``).

    Returns:
        Settlement price as a Python ``float``.

    Raises:
        EchelonError IND-005: when the row lacks a ``settlement`` field.
            Fail-loud — silently substituting ``close`` would corrupt
            carry signals on days where mid-vs-mark slippage matters.
    """
    if "settlement" not in bar_row.index:
        # Re-use the column-contract violation code; cast to a 1-row
        # DataFrame so the existing helper can list present columns.
        _require_columns(
            pd.DataFrame([bar_row]),
            ["settlement"],
            calculator="extract_settlement",
        )
    return float(bar_row["settlement"])


def front_back_settlements(curve_snapshot: pd.DataFrame) -> tuple[float, float]:
    """Return ``(settlement_front, settlement_back)`` from a curve snapshot.

    The snapshot must be sorted by ``expiry_date`` ascending (this is the
    canonical ordering returned by
    :func:`echolon.data.loaders.chain_composer.get_curve_snapshot`).

    Args:
        curve_snapshot: DataFrame with at least 2 rows and a ``settlement``
            column. iloc[0] is front, iloc[1] is back (second-nearest).

    Returns:
        Tuple of ``(front_settlement, back_settlement)``.

    Raises:
        EchelonError IND-005: when the snapshot lacks a ``settlement``
            column.
        ValueError: when the snapshot has fewer than 2 contracts — carry
            requires a two-point basis.
    """
    _require_columns(curve_snapshot, ["settlement"], calculator="front_back_settlements")
    if len(curve_snapshot) < 2:
        raise ValueError(
            f"front_back_settlements: snapshot has {len(curve_snapshot)} contracts, "
            "need at least 2 (front + back) — caller should skip-day or extend chain"
        )
    front = float(curve_snapshot.iloc[0]["settlement"])
    back = float(curve_snapshot.iloc[1]["settlement"])
    return front, back


def days_to_expiry_pair(curve_snapshot: pd.DataFrame) -> tuple[int, int]:
    """Return ``(days_to_expiry_front, days_to_expiry_back)`` from the snapshot.

    Args:
        curve_snapshot: DataFrame with at least 2 rows and a
            ``days_to_expiry`` column.

    Returns:
        Tuple of ``(front_dte, back_dte)`` as integers.
    """
    _require_columns(curve_snapshot, ["days_to_expiry"], calculator="days_to_expiry_pair")
    if len(curve_snapshot) < 2:
        raise ValueError(
            f"days_to_expiry_pair: snapshot has {len(curve_snapshot)} contracts, "
            "need at least 2"
        )
    front_dte = int(curve_snapshot.iloc[0]["days_to_expiry"])
    back_dte = int(curve_snapshot.iloc[1]["days_to_expiry"])
    return front_dte, back_dte
