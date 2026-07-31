"""Load and view immutable panel snapshots."""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

from .models import CurvePoint, InstrumentMeta, PanelManifest
from .sector import resolve_sector_asof


BAR_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "settle",
    "open_raw",
    "high_raw",
    "low_raw",
    "close_raw",
    "settle_raw",
    "open_adj",
    "high_adj",
    "low_adj",
    "close_adj",
    "settle_adj",
    "adj_factor",
    "volume",
    "open_interest",
    "contract",
    "amount",
    "total_mv",
    "float_mv",
    "suspended",
    "limit_up_price",
    "limit_down_price",
]

CONTRACT_COLUMNS = [
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "volume",
    "open_interest",
    "contract",
]

CURVE_COLUMNS = [
    "near_contract",
    "near_settle",
    "far_contract",
    "far_settle",
    "days_between",
]

INVENTORY_COLUMNS = ["receipts", "receipts_chg", "unit"]

POSITIONING_COLUMNS = ["long_oi_top20", "short_oi_top20", "net_share"]

FUNDAMENTALS_COLUMNS = [
    "report_period",
    "ann_date",
    "net_profit_q",
    "revenue_q",
    "total_equity",
    "total_assets",
    "ocf_q",
    "net_profit_ttm",
    "revenue_ttm",
    "ocf_ttm",
]

ESTIMATES_COLUMNS = [
    "consensus_eps_fy1",
    "consensus_count",
    "revision_score",
    "guidance_surprise",
]

SECTOR_MEMBERSHIP_COLUMNS = ["instrument", "l1_code", "in_date", "out_date"]


def _parse_date(value: str | dt.date) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_csv_with_date(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "date" not in df.columns:
        raise ValueError(f"{path} missing required date column")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.set_index("date").sort_index()


class PanelView:
    """Read-only view of all panel facts known as of one date."""

    def __init__(self, panel: "PanelData", date: dt.date) -> None:
        self._panel = panel
        self.date = date

    @property
    def instruments(self) -> tuple[str, ...]:
        """Normalized instruments in the panel's stable manifest order."""
        instruments = tuple(self._panel.instruments)
        normalized = tuple(str(instrument).strip().lower() for instrument in instruments)
        if instruments != normalized or len(set(instruments)) != len(instruments):
            raise ValueError("panel instruments must be unique normalized identifiers")
        if set(instruments) != set(self._panel._bars):
            raise ValueError("panel instruments and bar families are inconsistent")
        return instruments

    @property
    def calendar(self) -> tuple[dt.date, ...]:
        """Immutable union calendar in strictly increasing normalized order."""
        calendar = tuple(self._panel.calendar)
        if any(not isinstance(date, dt.date) for date in calendar):
            raise ValueError("panel calendar must contain date values")
        if tuple(sorted(set(calendar))) != calendar:
            raise ValueError("panel calendar must be unique and strictly increasing")
        if self.date not in calendar:
            raise ValueError(f"view date {self.date.isoformat()} is absent from panel calendar")
        return calendar

    @property
    def snapshot_version(self) -> str:
        """Immutable snapshot identity shared with the underlying panel."""
        version = self._panel.snapshot_version
        if not isinstance(version, str) or not version:
            raise ValueError("panel snapshot_version must be a non-empty string")
        if self._panel.manifest.version != version:
            raise ValueError("panel manifest and snapshot_version are inconsistent")
        return version

    @property
    def date_index(self) -> int:
        """Zero-based location of this view date in the union calendar."""
        return self.calendar.index(self.date)

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        if lookback <= 0:
            raise ValueError("lookback must be positive")
        instrument_id = instrument.lower()
        if instrument_id not in self._panel._bars:
            raise KeyError(instrument)
        bars = self._panel._bars[instrument_id]
        visible = bars.loc[bars.index <= self.date, BAR_COLUMNS]
        return visible.tail(lookback).copy()

    def current_bar(self, instrument: str) -> pd.Series | None:
        """Return the instrument's main bar on exactly the view date.

        Unlike :meth:`bars`, this method never carries a prior session forward.
        It is therefore the execution-grade API for union-calendar consumers.
        """
        instrument_id = instrument.lower()
        if instrument_id not in self._panel._bars:
            raise KeyError(instrument)
        bars = self._panel._bars[instrument_id]
        if self.date not in bars.index:
            return None
        rows = bars.loc[[self.date], BAR_COLUMNS]
        if len(rows) != 1:
            raise ValueError(
                f"expected one main bar for {instrument_id} on {self.date.isoformat()}, "
                f"found {len(rows)}"
            )
        return rows.iloc[0].copy()

    def contract_bar(self, instrument: str, contract: str) -> pd.Series | None:
        """Return the raw row for a specific listed contract on the view date."""
        instrument_id = instrument.lower()
        contracts = self._panel._contracts.get(instrument_id)
        if contracts is None or self.date not in contracts.index:
            return None
        rows = contracts.loc[[self.date]]
        match = rows[rows["contract"].astype(str) == str(contract)]
        if match.empty:
            return None
        if len(match) != 1:
            raise ValueError(
                f"expected one {contract} row for {instrument_id} on "
                f"{self.date.isoformat()}, found {len(match)}"
            )
        return match.iloc[0].copy()

    def contract_bar_asof(self, instrument: str, contract: str) -> pd.Series | None:
        """Return the latest visible row belonging to one exact contract.

        This accessor supports valuation carry-forward only. Execution code
        must use :meth:`contract_bar`, whose date contract is exact.
        """
        instrument_id = instrument.lower()
        candidates: list[tuple[int, pd.DataFrame]] = []
        contracts = self._panel._contracts.get(instrument_id)
        if contracts is not None:
            candidates.append((0, contracts.loc[contracts.index <= self.date]))
        bars = self._panel._bars.get(instrument_id)
        if bars is None:
            raise KeyError(instrument)
        candidates.append((1, bars.loc[bars.index <= self.date]))
        resolved: list[tuple[dt.date, int, pd.Series]] = []
        for source_rank, frame in candidates:
            match = frame[frame["contract"].astype(str) == str(contract)]
            if match.empty:
                continue
            latest_date = match.index.max()
            latest = match.loc[match.index == latest_date]
            if len(latest) != 1:
                raise ValueError(
                    f"expected one {contract} row for {instrument_id} on "
                    f"{latest_date.isoformat()}, found {len(latest)}"
                )
            resolved.append((latest_date, source_rank, latest.iloc[0]))
        if not resolved:
            return None
        _, _, row = max(resolved, key=lambda item: (item[0], -item[1]))
        return row.copy()

    def contracts_history(self, instrument: str, lookback: int) -> pd.DataFrame:
        """Return complete listed-contract curves for recent visible dates.

        ``lookback`` counts unique trading dates, not contract rows. The result
        therefore contains every listed contract row for each selected date,
        ordered by ascending date. Missing instruments return an empty frame;
        non-positive lookbacks raise :class:`ValueError`.
        """
        if lookback <= 0:
            raise ValueError("lookback must be positive")
        contracts = self._panel._contracts.get(instrument.lower())
        if contracts is None:
            return pd.DataFrame(columns=CONTRACT_COLUMNS)
        visible = contracts.loc[contracts.index <= self.date, CONTRACT_COLUMNS]
        selected_dates = visible.index.unique()[-lookback:]
        return visible.loc[visible.index.isin(selected_dates)].copy()

    def curve_history(self, instrument: str, lookback: int) -> pd.DataFrame:
        """Return up to ``lookback`` curve rows dated on or before the view date.

        Mirrors :meth:`bars` no-lookahead semantics for the near/far curve
        series so curve-history signals (basis momentum, carry change) cannot
        read past the view date by construction. Instruments without a curve
        file return an empty frame with the canonical curve columns.
        """
        if lookback <= 0:
            raise ValueError("lookback must be positive")
        instrument_id = instrument.lower()
        curves = self._panel._curves.get(instrument_id)
        if curves is None:
            return pd.DataFrame(columns=CURVE_COLUMNS)
        visible = curves.loc[curves.index <= self.date, CURVE_COLUMNS]
        return visible.tail(lookback).copy()

    def inventory_history(self, instrument: str, lookback: int) -> pd.DataFrame:
        """Return published inventory rows visible on or before the view date.

        A date-T row is visible in a date-T view, matching bars. Downstream
        execution code remains responsible for the binding T+1 timing rule.
        """
        return self._optional_history(
            instrument, lookback, self._panel._inventory, INVENTORY_COLUMNS
        )

    def positioning_history(self, instrument: str, lookback: int) -> pd.DataFrame:
        """Return published top-20 positioning rows on or before the view date."""
        return self._optional_history(
            instrument, lookback, self._panel._positioning, POSITIONING_COLUMNS
        )

    def fundamentals_history(
        self, instrument: str, lookback: int
    ) -> pd.DataFrame:
        """Return observation-dated fundamental rows visible to this view."""
        return self._optional_history(
            instrument,
            lookback,
            self._panel._fundamentals,
            FUNDAMENTALS_COLUMNS,
        )

    def estimates_history(
        self, instrument: str, lookback: int
    ) -> pd.DataFrame:
        """Return observation-dated estimate rows visible to this view."""
        return self._optional_history(
            instrument,
            lookback,
            self._panel._estimates,
            ESTIMATES_COLUMNS,
        )

    def universe(self) -> list[str]:
        """Return instruments eligible on exactly this view date."""
        membership = self._panel._universe
        if membership.empty:
            return []
        eligible = membership.loc[
            membership["date"].eq(self.date), "instrument"
        ]
        return sorted(eligible.astype(str).str.lower().unique())

    def sector_asof(self, instrument: str) -> str | None:
        """Return the point-in-time sector code, falling back to metadata."""
        meta = self.meta(instrument)
        return resolve_sector_asof(
            self._panel._sector_membership,
            instrument,
            self.date,
            fallback=meta.sector,
        )

    def _optional_history(
        self,
        instrument: str,
        lookback: int,
        histories: dict[str, pd.DataFrame],
        columns: list[str],
    ) -> pd.DataFrame:
        if lookback <= 0:
            raise ValueError("lookback must be positive")
        frame = histories.get(instrument.lower())
        if frame is None:
            return pd.DataFrame(columns=columns)
        visible = frame.loc[frame.index <= self.date, columns]
        return visible.tail(lookback).copy()

    def curve(self, instrument: str) -> CurvePoint | None:
        instrument_id = instrument.lower()
        curves = self._panel._curves.get(instrument_id)
        if curves is None or self.date not in curves.index:
            return None
        row = curves.loc[self.date]
        return CurvePoint(
            near_contract=str(row["near_contract"]),
            near_settle=float(row["near_settle"]),
            far_contract=str(row["far_contract"]),
            far_settle=float(row["far_settle"]),
            days_between=int(row["days_between"]),
        )

    def meta(self, instrument: str) -> InstrumentMeta:
        instrument_id = instrument.lower()
        if instrument_id not in self._panel._meta:
            raise KeyError(instrument)
        return self._panel._meta[instrument_id]


class PanelData:
    """Immutable multi-instrument daily panel loaded from a snapshot directory."""

    def __init__(
        self,
        *,
        snapshot_dir: Path | None,
        manifest: PanelManifest,
        bars: dict[str, pd.DataFrame],
        curves: dict[str, pd.DataFrame],
        contracts: dict[str, pd.DataFrame],
        meta: dict[str, InstrumentMeta],
        inventory: dict[str, pd.DataFrame] | None = None,
        positioning: dict[str, pd.DataFrame] | None = None,
        fundamentals: dict[str, pd.DataFrame] | None = None,
        estimates: dict[str, pd.DataFrame] | None = None,
        universe: pd.DataFrame | None = None,
        sector_membership: pd.DataFrame | None = None,
    ) -> None:
        self.snapshot_dir = snapshot_dir
        self.manifest = manifest
        self.instruments = list(manifest.instruments)
        self.snapshot_version = manifest.version
        self._bars = {
            instrument: _normalize_bar_frame(frame)
            for instrument, frame in bars.items()
        }
        self._curves = curves
        self._contracts = contracts
        self._meta = meta
        self._inventory = inventory or {}
        self._positioning = positioning or {}
        self._fundamentals = fundamentals or {}
        self._estimates = estimates or {}
        self._universe = _normalize_universe(universe)
        self._sector_membership = _normalize_sector_membership(sector_membership)
        self.calendar = self._build_calendar()

    @classmethod
    def load(cls, snapshot_dir: Path) -> "PanelData":
        snapshot_path = Path(snapshot_dir)
        manifest_path = snapshot_path / "manifest.json"
        manifest = PanelManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        cls._verify_manifest_hashes(snapshot_path, manifest)

        bars = {
            instrument: _normalize_bar_frame(_read_csv_with_date(snapshot_path / "bars" / f"{instrument}.csv"))
            for instrument in manifest.instruments
        }
        curves: dict[str, pd.DataFrame] = {}
        contracts: dict[str, pd.DataFrame] = {}
        for instrument in manifest.instruments:
            curve_path = snapshot_path / "curves" / f"{instrument}.csv"
            if curve_path.exists():
                curves[instrument] = _read_csv_with_date(curve_path)
            contracts_path = snapshot_path / "contracts" / f"{instrument}.csv"
            if contracts_path.exists():
                contracts[instrument] = _normalize_contract_frame(_read_csv_with_date(contracts_path))

        inventory = cls._load_optional_histories(
            snapshot_path, manifest, "inventory", INVENTORY_COLUMNS
        )
        positioning = cls._load_optional_histories(
            snapshot_path, manifest, "positioning", POSITIONING_COLUMNS
        )
        fundamentals = cls._load_optional_histories(
            snapshot_path, manifest, "fundamentals", FUNDAMENTALS_COLUMNS
        )
        estimates = cls._load_optional_histories(
            snapshot_path, manifest, "estimates", ESTIMATES_COLUMNS
        )
        membership_path = snapshot_path / "universe" / "membership.csv"
        if "universe/membership.csv" in manifest.files:
            universe = pd.read_csv(membership_path)
        else:
            universe = None
        sector_membership_path = snapshot_path / "universe" / "sw_membership.csv"
        if "universe/sw_membership.csv" in manifest.files:
            sector_membership = pd.read_csv(sector_membership_path)
        else:
            sector_membership = None

        meta = cls._load_meta(snapshot_path / "meta" / "instruments.csv")
        for instrument in manifest.instruments:
            if instrument not in meta:
                raise ValueError(f"missing metadata for instrument {instrument}")

        return cls(
            snapshot_dir=snapshot_path,
            manifest=manifest,
            bars=bars,
            curves=curves,
            contracts=contracts,
            meta=meta,
            inventory=inventory,
            positioning=positioning,
            fundamentals=fundamentals,
            estimates=estimates,
            universe=universe,
            sector_membership=sector_membership,
        )

    @staticmethod
    def _load_optional_histories(
        snapshot_dir: Path,
        manifest: PanelManifest,
        family: str,
        required_columns: list[str],
    ) -> dict[str, pd.DataFrame]:
        histories: dict[str, pd.DataFrame] = {}
        for instrument in manifest.instruments:
            relpath = f"{family}/{instrument}.csv"
            if relpath not in manifest.files:
                continue
            frame = _read_csv_with_date(snapshot_dir / relpath)
            missing = set(required_columns).difference(frame.columns)
            if missing:
                raise ValueError(f"{relpath} missing canonical columns: {sorted(missing)}")
            histories[instrument] = frame
        return histories

    @staticmethod
    def _verify_manifest_hashes(snapshot_dir: Path, manifest: PanelManifest) -> None:
        for relpath, expected_hash in manifest.files.items():
            path = snapshot_dir / relpath
            if not path.exists():
                raise ValueError(f"manifest file missing: {relpath}")
            actual_hash = _sha256(path)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"manifest hash mismatch for {relpath}: "
                    f"expected {expected_hash}, got {actual_hash}"
                )

    @staticmethod
    def _load_meta(path: Path) -> dict[str, InstrumentMeta]:
        df = pd.read_csv(path)
        records: dict[str, InstrumentMeta] = {}
        for row in df.to_dict(orient="records"):
            normalized = {key: _none_if_nan(value) for key, value in row.items()}
            instrument_id = str(normalized["instrument_id"]).lower()
            records[instrument_id] = InstrumentMeta(
                instrument_id=instrument_id,
                sector=str(normalized["sector"]),
                multiplier=float(normalized["multiplier"]),
                tick=float(normalized["tick"]),
                margin_rate=float(normalized["margin_rate"]),
                commission=float(normalized["commission"]),
                commission_type=str(normalized["commission_type"]),
                close_today_commission=(
                    None
                    if normalized["close_today_commission"] is None
                    else float(normalized["close_today_commission"])
                ),
                currency=str(normalized["currency"]),
                min_order_size=float(normalized.get("min_order_size") or 1.0),
                t_plus_one=_as_bool(normalized.get("t_plus_one"), default=False),
                stamp_duty_rate=float(
                    normalized.get("stamp_duty_rate") or 0.0
                ),
                transfer_fee_rate=float(
                    normalized.get("transfer_fee_rate") or 0.0
                ),
                min_commission=float(
                    normalized.get("min_commission") or 0.0
                ),
            )
        return records

    def _build_calendar(self) -> list[dt.date]:
        dates: set[dt.date] = set()
        for bars in self._bars.values():
            dates.update(bars.index)
        return sorted(dates)

    def view(self, date: dt.date | str) -> PanelView:
        view_date = _parse_date(date)
        if view_date not in self.calendar:
            raise KeyError(view_date.isoformat())
        return PanelView(self, view_date)


def _none_if_nan(value: Any) -> Any:
    if pd.isna(value):
        return None
    if value == "":
        return None
    return value


def _normalize_bar_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in ("open", "high", "low", "close", "settle"):
        raw = f"{column}_raw"
        adj = f"{column}_adj"
        if raw not in out:
            out[raw] = out[column]
        if adj not in out:
            out[adj] = out[column]
        out[column] = out[adj]
    if "adj_factor" not in out:
        out["adj_factor"] = 1.0
    for column in ("amount", "total_mv", "float_mv"):
        if column not in out:
            out[column] = float("nan")
    if "suspended" not in out:
        out["suspended"] = 0.0
    if "limit_up_price" not in out:
        out["limit_up_price"] = float("nan")
    if "limit_down_price" not in out:
        out["limit_down_price"] = float("nan")
    return out


def _normalize_universe(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["date", "instrument"])
    out = frame.copy()
    if "instrument" not in out and "ts_code" in out:
        out = out.rename(columns={"ts_code": "instrument"})
    missing = {"date", "instrument"}.difference(out.columns)
    if missing:
        raise ValueError(
            f"universe/membership.csv missing columns: {sorted(missing)}"
        )
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out["instrument"] = out["instrument"].astype(str).str.lower()
    return out[["date", "instrument"]].sort_values(
        ["date", "instrument"]
    )


def _normalize_sector_membership(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=SECTOR_MEMBERSHIP_COLUMNS)
    missing = set(SECTOR_MEMBERSHIP_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(
            f"universe/sw_membership.csv missing columns: {sorted(missing)}"
        )
    out = frame.copy()
    out["instrument"] = out["instrument"].astype(str).str.lower()
    return out[SECTOR_MEMBERSHIP_COLUMNS].sort_values(
        ["instrument", "in_date"]
    )


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"invalid boolean metadata value: {value}")


def _normalize_contract_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "contract" not in out and "symbol" in out:
        out["contract"] = out["symbol"]
    if "symbol" not in out and "contract" in out:
        out["symbol"] = out["contract"]
    return out
