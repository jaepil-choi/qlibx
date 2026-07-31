"""Point-in-time sector membership resolution."""
from __future__ import annotations

import datetime as dt

import pandas as pd


def _parse_membership_dates(values: pd.Series, *, column: str) -> pd.Series:
    """Parse YYYYMMDD membership dates, preserving only genuine empties as NaT."""
    genuinely_empty = values.isna()
    text = values.astype(str).str.strip()
    if pd.api.types.is_float_dtype(values.dtype):
        text = text.str.removesuffix(".0")
    genuinely_empty |= text.eq("")
    try:
        return pd.to_datetime(
            text.mask(genuinely_empty),
            format="%Y%m%d",
            errors="raise",
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid non-empty {column}; expected YYYYMMDD") from exc


def resolve_sector_asof(
    membership: pd.DataFrame,
    instrument: str,
    date: dt.date | str,
    *,
    fallback: str | None = None,
) -> str | None:
    """Return the sector active on ``date``, or the explicit fallback."""
    required = {"instrument", "l1_code", "in_date", "out_date"}
    missing = required.difference(membership.columns)
    if missing:
        raise ValueError(f"sector membership missing columns: {sorted(missing)}")
    view_date = pd.Timestamp(date)
    frame = membership.loc[
        membership["instrument"].astype(str).str.lower().eq(instrument.lower())
    ].copy()
    frame["in_date"] = _parse_membership_dates(frame["in_date"], column="in_date")
    frame["out_date"] = _parse_membership_dates(frame["out_date"], column="out_date")
    active = frame.loc[
        frame["in_date"].le(view_date)
        & (frame["out_date"].isna() | frame["out_date"].ge(view_date))
    ]
    if active.empty:
        return fallback
    sectors = active["l1_code"].dropna().astype(str).unique()
    if len(sectors) != 1:
        raise ValueError(
            f"ambiguous sector membership for {instrument} on {view_date.date()}"
        )
    return str(sectors[0])
