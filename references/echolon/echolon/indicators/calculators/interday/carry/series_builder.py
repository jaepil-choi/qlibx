"""
Carry SERIES builder — the forward curve as per-date carry indicator columns
============================================================================

The five carry indicators (:mod:`echolon.indicators.calculators.interday.carry`)
are SCALAR: one same-date curve snapshot -> one value. The backtest pipeline,
however, needs them as per-DATE columns alongside the per-contract ta-lib
indicators in ``strategy_indicators.csv``. This module is the vectorized series
builder: it reads the on-disk forward curve (``sort_by_date.csv`` — every
contract's settlement per date) ONCE, date-major, and emits the 5 carry
indicators as a date-indexed frame, computing the identical formulas the scalar
calculators use.

Behavior-preserving port of the former qorka ``carry_basis.build_carry_basis_series``
(the prior Path-B injector source, since removed — echolon is now the single source
of carry computation) — same windows, sign conventions, float floors, and
weekday-approximation expiry, so the carry values entering the backtest are
unchanged. Two spellings differ from that source to honor echolon's
NO_ERROR_HANDLING policy (the COMPUTED VALUES are byte-identical):

  1. Contract parsing uses a vectorized regex MASK, not a ``try/except
     ValueError`` drop — non-conforming codes (wrong shape, month outside 1..12)
     are filtered, exactly the set qorka's exception path drops.
  2. ``open_interest`` is read only when the column is present (echolon's own
     "when present" convention for OI, per ``chain_composer.get_curve_snapshot``);
     no ``.get(col, default)`` fallback. ``back_open_interest`` (the back leg's
     OI) is emitted as a supporting byproduct — not a carry indicator, but the
     back-leg liquidity input the R&D basis analyzer needs, so the frame is a
     complete drop-in for the carry-basis series.

DEGENERATE DAYS -> NaN is a DELIBERATE DOMAIN SENTINEL, not error suppression: a
series builder and a scalar calculator are different contracts by design. The
scalar ``carry_front_back`` RAISES on a <2-contract / zero-spread day (correct —
the caller asked for one value); the series builder marks that single date NaN so
one bad day cannot abort the whole backtest. Numerically identical on every valid
day.
"""
from __future__ import annotations

import calendar as _calendar
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Windows — carry/utils.py DEFAULT_VOL_WINDOW / DEFAULT_Z_WINDOW /
# DEFAULT_CHANGE_LAG / DEFAULT_SLOPE_N (trading days).
_VOL_WINDOW = 20
_Z_WINDOW = 63
_CHANGE_LAG = 20
_SLOPE_N = 3
# Non-degenerate floors — risk_adj_carry / carry_z_3m (`> 0` alone passes for
# ~3e-17 float noise on a constant series and explodes the ratio).
_VOL_FLOOR = 1e-12
_SIGMA_FLOOR = 1e-12

# ^product(letters) + 4-digit YYMM$ — a conforming SHFE-style contract code.
_CONTRACT_RE_STR = r"[a-zA-Z]+\d{4}"

CARRY_INDICATOR_COLUMNS = (
    "carry_front_back",
    "curve_slope_near",
    "risk_adj_carry",
    "carry_z_3m",
    "carry_change_20d",
)

# Settlement/DTE/OI byproducts emitted alongside the 5 indicators (the scalar
# inputs the carry values are computed from, plus the back-leg open interest the
# R&D basis-liquidity analysis needs) — a complete drop-in for the carry-basis
# series.
_SUPPORTING_COLUMNS = (
    "settlement_front",
    "settlement_back",
    "days_to_expiry_front",
    "days_to_expiry_back",
    "back_open_interest",
)


def _expiry_date(year: int, month: int) -> date:
    """SHFE expiry = last trading day of the month BEFORE the delivery month
    (echolon ``markets/shfe/contract_rules.get_expiry_date``), approximated here
    as the last WEEKDAY of that prior month. Weekday-approx is verbatim from the
    qorka Path-B source so backtest carry values are unchanged; upgrading to the
    holiday-aware TradingCalendar is a separate, measured change."""
    if month == 1:
        ey, em = year - 1, 12
    else:
        ey, em = year, month - 1
    last_dom = _calendar.monthrange(ey, em)[1]
    d = date(ey, em, last_dom)
    while d.weekday() >= 5:  # Sat=5, Sun=6 -> step back to Friday
        d -= timedelta(days=1)
    return d


def _carry_front_back(settle_front: float, settle_back: float, dte_front: int, dte_back: int) -> float:
    """Annualized front-vs-back basis (scalar ``carry_front_back.py``):
    ``(settle_front/settle_back - 1) * 365 / (dte_back - dte_front)``.
    Sign: positive = backwardation (front > back) = LONG. Zero expiry-spread ->
    NaN sentinel (the scalar calc raises; the series builder marks the day)."""
    dte_diff = dte_back - dte_front
    if dte_diff == 0:
        return float("nan")
    return (settle_front / settle_back - 1.0) * 365.0 / dte_diff


def _curve_slope_near(settles: np.ndarray, dtes: np.ndarray) -> float:
    """``-slope`` of log(settlement) vs days_to_expiry over the nearest contracts
    (scalar ``curve_slope_near.py``; sign-flipped so positive = backwardation).
    Degenerate input (<2 points, non-positive settle, non-finite fit) -> NaN."""
    if len(settles) < 2 or np.any(settles <= 0):
        return float("nan")
    slope, _ = np.polyfit(dtes.astype(float), np.log(settles.astype(float)), deg=1)
    if not np.isfinite(slope):
        return float("nan")
    return float(-slope)


def build_carry_indicator_frame(
    asset: str, *, market: str = "SHFE", market_data_dir: Path
) -> pd.DataFrame:
    """Assemble the 5 carry indicators as a per-date DataFrame.

    Args:
        asset: instrument dir name (e.g. ``"aluminum"``), as resolved by the
            indicator processor (``ctx.instrument_name`` — the same token
            ``load_contract_ohlcv(asset=...)`` uses).
        market: market code (default ``"SHFE"``). Echolon-native path
            convention, matching ``load_ohlcv`` / ``get_curve_snapshot``.
        market_data_dir: the ROOT market-data dir (``paths.market_data_dir`` —
            does NOT include the market segment). The curve file is resolved as
            ``market_data_dir / MARKET / asset / "sort_by_date.csv"``.

    Returns:
        DataFrame indexed by trading date (DatetimeIndex) with
        :data:`CARRY_INDICATOR_COLUMNS` plus the settlement/dte byproducts in
        :data:`_SUPPORTING_COLUMNS`. Degenerate days are NaN.
    """
    # Resolve the date-major curve file the echolon-native way
    # ({market_data_dir}/{MARKET}/{asset}/sort_by_date.csv — same layout as
    # ohlcv_loader.load_ohlcv). The raw read below is kept byte-identical to the
    # qorka Path-B source so carry values are unchanged; only path resolution is
    # echolon-native.
    sbd_path = Path(market_data_dir) / market.upper() / asset / "sort_by_date.csv"
    if not sbd_path.exists():
        raise FileNotFoundError(f"sort_by_date.csv missing for {asset}: {sbd_path}")

    df = pd.read_csv(
        sbd_path, usecols=lambda c: c in ("contract", "date", "settlement", "open_interest")
    )
    df = df.dropna(subset=["contract", "date", "settlement"])
    df["date"] = pd.to_datetime(df["date"].astype(int).astype(str), format="%Y%m%d")
    # OI is optional in the schema (chain_composer reads it "when present"); emit
    # back_open_interest only if the column exists, per-row NaN otherwise.
    has_oi = "open_interest" in df.columns

    # Parse contract -> (year, month) -> expiry, VECTORIZED (no try/except). The
    # regex mask keeps only conforming codes; .str[:2]/[2:4] are then guaranteed
    # 2-digit ints, so the month filter + year split cannot raise.
    codes = df["contract"].astype(str)
    df = df[codes.str.fullmatch(_CONTRACT_RE_STR)].copy()
    yymm = df["contract"].astype(str).str.extract(r"(\d{4})$")[0]
    yy = yymm.str[:2].astype(int)
    mo = yymm.str[2:4].astype(int)
    month_ok = mo.between(1, 12)
    df = df[month_ok.to_numpy()].copy()
    yy = yy[month_ok]
    mo = mo[month_ok]
    df["_m"] = mo.to_numpy()
    df["_y"] = np.where(yy.to_numpy() <= 50, 2000 + yy.to_numpy(), 1900 + yy.to_numpy())
    df["_expiry"] = [_expiry_date(int(y), int(m)) for y, m in zip(df["_y"], df["_m"])]

    rows = []
    # Per date: active chain = not-yet-expired contracts, sorted by expiry ascending
    # (== (year, month) ascending). front=iloc[0], back=iloc[1] — get_curve_snapshot
    # ordering. No OI filter (echolon takes all active, expiry-sorted).
    for d, g in df.groupby("date", sort=True):
        d_date = d.date()
        g = g[[e >= d_date for e in g["_expiry"]]]
        if len(g) < 2:
            rows.append({"date": d, "settlement_front": np.nan})
            continue
        g = g.sort_values(["_y", "_m"]).reset_index(drop=True)
        front, back = g.iloc[0], g.iloc[1]
        dte_front = (front["_expiry"] - d_date).days
        dte_back = (back["_expiry"] - d_date).days
        near = g.head(_SLOPE_N)
        back_oi = float(back["open_interest"]) if (has_oi and pd.notna(back["open_interest"])) else np.nan
        rows.append({
            "date": d,
            "settlement_front": float(front["settlement"]),
            "settlement_back": float(back["settlement"]),
            "days_to_expiry_front": dte_front,
            "days_to_expiry_back": dte_back,
            "back_open_interest": back_oi,
            "carry_front_back": _carry_front_back(
                float(front["settlement"]), float(back["settlement"]), dte_front, dte_back
            ),
            "curve_slope_near": _curve_slope_near(
                near["settlement"].to_numpy(),
                np.array([(e - d_date).days for e in near["_expiry"]]),
            ),
        })

    out = pd.DataFrame(rows).set_index("date").sort_index()

    # History-based indicators — vectorized over the per-date series, mirroring the
    # scalar formulas exactly.
    # risk_adj_carry = carry_front_back / std(pct_change(front_settlement), 20, ddof=1)
    front_ret = out["settlement_front"].pct_change()
    vol = front_ret.rolling(_VOL_WINDOW).std(ddof=1)
    vol = vol.where(vol > _VOL_FLOOR)  # sub-floor / NaN -> NaN (scalar calc raises)
    out["risk_adj_carry"] = out["carry_front_back"] / vol
    # carry_z_3m = (carry - rolling_mean63) / rolling_std63(ddof=1)
    mu = out["carry_front_back"].rolling(_Z_WINDOW).mean()
    sigma = out["carry_front_back"].rolling(_Z_WINDOW).std(ddof=1)
    sigma = sigma.where(sigma > _SIGMA_FLOOR)
    out["carry_z_3m"] = (out["carry_front_back"] - mu) / sigma
    # carry_change_20d = carry_today - carry_(t-20)
    out["carry_change_20d"] = out["carry_front_back"] - out["carry_front_back"].shift(_CHANGE_LAG)

    return out
