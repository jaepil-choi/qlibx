"""Panel snapshot quality checks."""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from typing import Any

import pandas as pd

from .models import QCCheck, QCReport


PIT_RESTATEMENT_MESSAGE = (
    "Fundamental values may include later restatements; announcement dates "
    "are approximate first-observation dates (pit_status=ann_date_approx)."
)


def _contract_month(contract: str) -> int | None:
    match = re.search(r"(\d{4})", str(contract))
    if match is None:
        return None
    return int(match.group(1))


def _add_check(
    checks: list[QCCheck],
    *,
    check_id: str,
    severity: str,
    message: str,
    instrument: str | None,
    date: dt.date | None,
    value: float | None = None,
    waived: bool = False,
    waiver_reason: str | None = None,
    waiver_approved_by: str | None = None,
) -> None:
    checks.append(
        QCCheck(
            check_id=check_id,
            severity=severity,
            message=message,
            instrument=instrument,
            date=date,
            value=value,
            waived=waived,
            waiver_reason=waiver_reason,
            waiver_approved_by=waiver_approved_by,
        )
    )


def run_panel_qc(
    *,
    snapshot: str,
    bars: dict[str, pd.DataFrame],
    curves: dict[str, pd.DataFrame],
    roll_gap_stats: dict | None = None,
    waivers: Mapping[tuple[str, dt.date | None, str], str | Mapping[str, Any]] | None = None,
    inventory: dict[str, pd.DataFrame] | None = None,
    positioning: dict[str, pd.DataFrame] | None = None,
    trading_calendars: Mapping[str, list[dt.date]] | None = None,
    fundamentals: dict[str, pd.DataFrame] | None = None,
    estimates: dict[str, pd.DataFrame] | None = None,
    universe: pd.DataFrame | None = None,
    delisted_roster: pd.DataFrame | None = None,
    source_manifest: Mapping[str, Any] | None = None,
    instrument_meta: Mapping[str, Any] | None = None,
) -> QCReport:
    """Run S12 QC checks over in-memory panel data."""
    checks: list[QCCheck] = []
    for instrument, frame in bars.items():
        meta = (instrument_meta or {}).get(instrument)
        tick = float(meta.tick) if meta is not None else 0.0
        _check_bars(
            instrument,
            frame,
            checks,
            waivers or {},
            tick=tick,
            trading_calendar=list(
                (trading_calendars or {}).get(instrument, [])
            ),
        )
    for instrument, frame in curves.items():
        _check_curves(instrument, frame, checks)
    for instrument, frame in (inventory or {}).items():
        _check_inventory(
            instrument,
            frame,
            list((trading_calendars or {}).get(instrument, [])),
            checks,
            waivers or {},
        )
    for instrument, frame in (positioning or {}).items():
        _check_optional_history(
            family="positioning",
            instrument=instrument,
            frame=frame,
            calendar=list((trading_calendars or {}).get(instrument, [])),
            checks=checks,
            waivers=waivers or {},
        )
    calendar = sorted(
        {
            _date_value(date)
            for frame in bars.values()
            for date in frame.index
        }
    )
    _check_pit_consistency(
        fundamentals or {}, estimates or {}, calendar, checks, waivers or {}
    )
    if universe is not None:
        normalized_universe = _normalize_universe(universe)
        _check_survivorship_coverage(
            normalized_universe,
            delisted_roster,
            calendar,
            checks,
            waivers or {},
        )
        _check_universe_coverage(
            normalized_universe,
            fundamentals,
            checks,
            waivers or {},
        )
    if (source_manifest or {}).get("pit_status") == "ann_date_approx":
        _add_check(
            checks,
            check_id="pit_restatement_caveat",
            severity="WARN",
            message=PIT_RESTATEMENT_MESSAGE,
            instrument=None,
            date=None,
        )

    if any(check.severity == "ERROR" and not check.waived for check in checks):
        status = "FAIL"
    elif checks:
        status = "PASS_WITH_WARNINGS"
    else:
        status = "PASS"
    return QCReport(snapshot=snapshot, status=status, checks=checks, roll_gap_stats=roll_gap_stats or {})


def _check_bars(
    instrument: str,
    frame: pd.DataFrame,
    checks: list[QCCheck],
    waivers: Mapping[tuple[str, dt.date | None, str], str | Mapping[str, Any]],
    *,
    tick: float,
    trading_calendar: list[dt.date],
) -> None:
    required_price_columns = ("open", "high", "low", "close", "settle")
    raw_price_columns = tuple(column for column in ("open_raw", "high_raw", "low_raw", "close_raw", "settle_raw") if column in frame)
    for date, row in frame.iterrows():
        date_value = date if isinstance(date, dt.date) else pd.Timestamp(date).date()
        for column in required_price_columns + raw_price_columns:
            value = float(row[column])
            if value <= 0:
                reason, approved_by = _waiver_details(
                    waivers.get((instrument, date_value, "price_positive"))
                )
                _add_check(
                    checks,
                    check_id="price_positive",
                    severity="ERROR",
                    message=f"{column} must be positive",
                    instrument=instrument,
                    date=date_value,
                    value=value,
                    waived=reason is not None and approved_by is not None,
                    waiver_reason=reason,
                    waiver_approved_by=approved_by,
                )
        volume = float(row["volume"])
        suspended = (
            pd.to_numeric(
                pd.Series([row.get("suspended", 0.0)]), errors="coerce"
            ).fillna(0.0).iloc[0]
            == 1.0
        )
        if volume == 0 and not suspended:
            _add_check(
                checks,
                check_id="volume_nonzero",
                severity="WARN",
                message="volume is zero on a trading day",
                instrument=instrument,
                date=date_value,
                value=volume,
            )
        close = float(row["close"])
        settle = float(row["settle"])
        if close > 0:
            divergence = abs(settle - close) / close
            if divergence > 0.08:
                reason, approved_by = _waiver_details(
                    waivers.get((instrument, date_value, "settle_close_divergence"))
                )
                _add_check(
                    checks,
                    check_id="settle_close_divergence",
                    severity="ERROR",
                    message="settle-close divergence exceeds hard threshold",
                    instrument=instrument,
                    date=date_value,
                    value=divergence,
                    waived=reason is not None and approved_by is not None,
                    waiver_reason=reason,
                    waiver_approved_by=approved_by,
                )
            elif divergence > 0.03:
                _add_check(
                    checks,
                    check_id="settle_close_divergence",
                    severity="WARN",
                    message="settle-close divergence exceeds threshold",
                    instrument=instrument,
                    date=date_value,
                    value=divergence,
                )

    has_equity_limits = (
        {"limit_up_price", "limit_down_price"}.issubset(frame.columns)
        and frame[["limit_up_price", "limit_down_price"]].notna().any().any()
    )
    if has_equity_limits:
        _check_equity_limit_bands(
            instrument,
            frame,
            tick,
            checks,
            waivers,
            trading_calendar,
        )
        return

    closes = pd.to_numeric(frame["close"], errors="coerce")
    returns = closes.pct_change().dropna().abs()
    for date, value in returns.items():
        date_value = date if isinstance(date, dt.date) else pd.Timestamp(date).date()
        if value > 0.12:
            reason, approved_by = _waiver_details(
                waivers.get((instrument, date_value, "daily_return_threshold"))
            )
            _add_check(
                checks,
                check_id="daily_return_threshold",
                severity="ERROR",
                message="daily absolute return exceeds hard threshold",
                instrument=instrument,
                date=date_value,
                value=float(value),
                waived=reason is not None and approved_by is not None,
                waiver_reason=reason,
                waiver_approved_by=approved_by,
            )
            continue
        if value <= 0.07:
            continue
        _add_check(
            checks,
            check_id="daily_return_threshold",
            severity="WARN",
            message="daily absolute return exceeds threshold",
            instrument=instrument,
            date=date_value,
            value=float(value),
        )


def _check_equity_limit_bands(
    instrument: str,
    frame: pd.DataFrame,
    tick: float,
    checks: list[QCCheck],
    waivers: Mapping[tuple[str, dt.date | None, str], str | Mapping[str, Any]],
    trading_calendar: list[dt.date],
) -> None:
    """Check raw close prices against exchange bands in RMB per share."""
    close_column = "close_raw" if "close_raw" in frame else "close"
    tolerance = tick / 2.0
    calendar_positions = {
        _date_value(date): position
        for position, date in enumerate(trading_calendar)
    }
    previous_trading_position: int | None = None
    consecutive_suspended = 0
    for date, row in frame.iterrows():
        date_value = _date_value(date)
        suspended = (
            pd.to_numeric(
                pd.Series([row.get("suspended", 0.0)]), errors="coerce"
            ).fillna(0.0).iloc[0]
            == 1.0
        )
        if suspended:
            consecutive_suspended += 1
            continue
        current_position = calendar_positions.get(date_value)
        if current_position is not None:
            gap_length = (
                current_position
                if previous_trading_position is None
                else current_position - previous_trading_position - 1
            )
            previous_trading_position = current_position
        else:
            gap_length = consecutive_suspended
        is_resumption = gap_length >= 10
        consecutive_suspended = 0
        close = pd.to_numeric(pd.Series([row[close_column]]), errors="coerce").iloc[0]
        upper = pd.to_numeric(
            pd.Series([row["limit_up_price"]]), errors="coerce"
        ).iloc[0]
        lower = pd.to_numeric(
            pd.Series([row["limit_down_price"]]), errors="coerce"
        ).iloc[0]
        if pd.isna(close) or pd.isna(upper) or pd.isna(lower):
            continue
        if is_resumption:
            _add_check(
                checks,
                check_id="limit_band_resumption_skip",
                severity="WARN",
                message=(
                    "exchange limit band skipped on first trading row after "
                    "at least 10 suspended trading days"
                ),
                instrument=instrument,
                date=date_value,
                value=float(gap_length),
            )
            continue
        if lower - tolerance <= close <= upper + tolerance:
            continue
        date_value = _date_value(date)
        reason, approved_by = _waiver_details(
            waivers.get((instrument, date_value, "equity_limit_band"))
        )
        distance = max(float(close - upper), float(lower - close), 0.0)
        _add_check(
            checks,
            check_id="equity_limit_band",
            severity="ERROR",
            message="raw close exceeds exchange limit band plus half tick",
            instrument=instrument,
            date=date_value,
            value=distance,
            waived=reason is not None and approved_by is not None,
            waiver_reason=reason,
            waiver_approved_by=approved_by,
        )


def _waiver_details(value: str | Mapping[str, Any] | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, str):
        return value, None
    reason = value.get("reason") or value.get("waiver_reason")
    approved_by = value.get("approved_by") or value.get("waiver_approved_by")
    reason_str = str(reason).strip() if reason is not None else ""
    approved_str = str(approved_by).strip() if approved_by is not None else ""
    return reason_str or None, approved_str or None


def _check_curves(instrument: str, frame: pd.DataFrame, checks: list[QCCheck]) -> None:
    for date, row in frame.iterrows():
        date_value = date if isinstance(date, dt.date) else pd.Timestamp(date).date()
        near_settle = float(row["near_settle"])
        far_settle = float(row["far_settle"])
        if near_settle <= 0 or far_settle <= 0:
            _add_check(
                checks,
                check_id="curve_settle_positive",
                severity="ERROR",
                message="curve settle prices must be positive",
                instrument=instrument,
                date=date_value,
                value=min(near_settle, far_settle),
            )
        near_month = _contract_month(str(row["near_contract"]))
        far_month = _contract_month(str(row["far_contract"]))
        if near_month is not None and far_month is not None and near_month >= far_month:
            _add_check(
                checks,
                check_id="curve_contract_order",
                severity="ERROR",
                message="near contract must expire before far contract",
                instrument=instrument,
                date=date_value,
                value=float(near_month),
            )


def _date_value(value: Any) -> dt.date:
    return value if isinstance(value, dt.date) else pd.Timestamp(value).date()


def _waived_error(
    checks: list[QCCheck],
    *,
    check_id: str,
    message: str,
    instrument: str,
    date: dt.date | None,
    value: float | None,
    waivers: Mapping[tuple[str, dt.date | None, str], str | Mapping[str, Any]],
) -> None:
    reason, approved_by = _waiver_details(waivers.get((instrument, date, check_id)))
    _add_check(
        checks,
        check_id=check_id,
        severity="ERROR",
        message=message,
        instrument=instrument,
        date=date,
        value=value,
        waived=reason is not None and approved_by is not None,
        waiver_reason=reason,
        waiver_approved_by=approved_by,
    )


def _check_optional_history(
    *,
    family: str,
    instrument: str,
    frame: pd.DataFrame,
    calendar: list[dt.date],
    checks: list[QCCheck],
    waivers: Mapping[tuple[str, dt.date | None, str], str | Mapping[str, Any]],
) -> None:
    duplicate_dates = frame.index[frame.index.duplicated()].unique()
    for date in duplicate_dates:
        date_value = _date_value(date)
        _waived_error(
            checks,
            check_id=f"{family}_duplicate_date",
            message=f"{family} contains duplicate dates",
            instrument=instrument,
            date=date_value,
            value=float((frame.index == date).sum()),
            waivers=waivers,
        )
    present = {_date_value(value) for value in frame.index}
    first_present = min(present) if present else None
    expected = [date for date in calendar if first_present is None or date >= first_present]
    missing = sorted(set(expected).difference(present))
    coverage = len(set(expected).intersection(present)) / len(expected) if expected else 1.0
    if missing and coverage < 0.95:
        _waived_error(
            checks,
            check_id=f"{family}_coverage",
            message=f"{family} is missing trading-calendar dates",
            instrument=instrument,
            date=missing[0],
            value=coverage,
            waivers=waivers,
        )
    elif missing and coverage < 0.995:
        _add_check(
            checks,
            check_id=f"{family}_coverage",
            severity="WARN",
            message=f"{family} coverage is below warning threshold",
            instrument=instrument,
            date=missing[0],
            value=coverage,
        )


def _check_inventory(
    instrument: str,
    frame: pd.DataFrame,
    calendar: list[dt.date],
    checks: list[QCCheck],
    waivers: Mapping[tuple[str, dt.date | None, str], str | Mapping[str, Any]],
) -> None:
    _check_optional_history(
        family="inventory",
        instrument=instrument,
        frame=frame,
        calendar=calendar,
        checks=checks,
        waivers=waivers,
    )
    if "unit" not in frame.columns:
        _waived_error(
            checks,
            check_id="inventory_unit_column_present",
            message="inventory requires a unit column",
            instrument=instrument,
            date=None,
            value=None,
            waivers=waivers,
        )
    else:
        for date, unit in frame["unit"].items():
            if pd.isna(unit) or not str(unit).strip():
                _waived_error(
                    checks,
                    check_id="inventory_unit_value_present",
                    message="inventory unit value must be present",
                    instrument=instrument,
                    date=_date_value(date),
                    value=None,
                    waivers=waivers,
                )
    if "receipts" in frame.columns:
        for date, receipts in pd.to_numeric(frame["receipts"], errors="coerce").items():
            if pd.notna(receipts) and receipts < 0:
                _waived_error(
                    checks,
                    check_id="inventory_receipts_nonnegative",
                    message="inventory receipts must be nonnegative",
                    instrument=instrument,
                    date=_date_value(date),
                    value=float(receipts),
                    waivers=waivers,
                )


def _check_pit_consistency(
    fundamentals: dict[str, pd.DataFrame],
    estimates: dict[str, pd.DataFrame],
    calendar: list[dt.date],
    checks: list[QCCheck],
    waivers: Mapping[tuple[str, dt.date | None, str], str | Mapping[str, Any]],
) -> None:
    if not calendar:
        return
    panel_end = max(calendar)
    for family, histories in (
        ("fundamentals", fundamentals),
        ("estimates", estimates),
    ):
        for instrument, frame in histories.items():
            for observation in frame.index:
                observation_date = _date_value(observation)
                if observation_date <= panel_end:
                    continue
                _waived_error(
                    checks,
                    check_id="pit_consistency",
                    message=(
                        f"{family} observation falls after panel calendar end"
                    ),
                    instrument=instrument,
                    date=observation_date,
                    value=float((observation_date - panel_end).days),
                    waivers=waivers,
                )


def _normalize_universe(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "instrument" not in out and "ts_code" in out:
        out = out.rename(columns={"ts_code": "instrument"})
    missing = {"date", "instrument"}.difference(out.columns)
    if missing:
        raise ValueError(f"universe missing columns: {sorted(missing)}")
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out["instrument"] = out["instrument"].astype(str).str.lower()
    return out[["date", "instrument"]]


def _check_survivorship_coverage(
    universe: pd.DataFrame,
    delisted_roster: pd.DataFrame | None,
    calendar: list[dt.date],
    checks: list[QCCheck],
    waivers: Mapping[tuple[str, dt.date | None, str], str | Mapping[str, Any]],
) -> None:
    if delisted_roster is None or delisted_roster.empty or not calendar:
        return
    roster = delisted_roster.copy()
    if "instrument" not in roster and "ts_code" in roster:
        roster = roster.rename(columns={"ts_code": "instrument"})
    missing = {"instrument", "delist_date"}.difference(roster.columns)
    if missing:
        raise ValueError(f"delisted roster missing columns: {sorted(missing)}")
    roster["instrument"] = roster["instrument"].astype(str).str.lower()
    roster["delist_date"] = pd.to_datetime(
        roster["delist_date"], errors="coerce"
    ).dt.date
    calendar_start, calendar_end = min(calendar), max(calendar)
    for row in roster.itertuples(index=False):
        delist_date = row.delist_date
        if (
            pd.isna(delist_date)
            or delist_date < calendar_start
            or delist_date > calendar_end
        ):
            continue
        present = universe.loc[
            universe["instrument"].eq(row.instrument)
            & universe["date"].lt(delist_date)
        ]
        if not present.empty:
            continue
        _waived_error(
            checks,
            check_id="survivorship_coverage",
            message="in-calendar delisted instrument lacks pre-delist membership",
            instrument=row.instrument,
            date=delist_date,
            value=0.0,
            waivers=waivers,
        )


def _check_universe_coverage(
    universe: pd.DataFrame,
    fundamentals: dict[str, pd.DataFrame] | None,
    checks: list[QCCheck],
    waivers: Mapping[tuple[str, dt.date | None, str], str | Mapping[str, Any]],
) -> None:
    counts = universe.groupby("date")["instrument"].nunique().sort_index()
    for position, (date, count) in enumerate(counts.items()):
        trailing = counts.iloc[max(0, position - 20) : position]
        if trailing.empty:
            continue
        median = float(trailing.median())
        if median <= 0 or float(count) >= median * 0.70:
            continue
        _waived_error(
            checks,
            check_id="universe_coverage",
            message="eligible count dropped more than 30% versus trailing median",
            instrument="universe",
            date=_date_value(date),
            value=float(count) / median,
            waivers=waivers,
        )
    if fundamentals is None:
        return
    normalized_histories = {
        instrument.lower(): frame for instrument, frame in fundamentals.items()
    }
    for date, rows in universe.groupby("date"):
        eligible = set(rows["instrument"])
        if not eligible:
            continue
        observed = 0
        for instrument in eligible:
            history = normalized_histories.get(instrument)
            if history is None or history.empty:
                continue
            if any(_date_value(value) <= date for value in history.index):
                observed += 1
        coverage = observed / len(eligible)
        if coverage >= 0.70:
            continue
        severity = "ERROR" if coverage < 0.50 else "WARN"
        if severity == "ERROR":
            _waived_error(
                checks,
                check_id="fundamental_coverage",
                message="fundamental coverage is below 50% of eligible names",
                instrument="universe",
                date=_date_value(date),
                value=coverage,
                waivers=waivers,
            )
        else:
            _add_check(
                checks,
                check_id="fundamental_coverage",
                severity="WARN",
                message="fundamental coverage is below 70% of eligible names",
                instrument="universe",
                date=_date_value(date),
                value=coverage,
            )
