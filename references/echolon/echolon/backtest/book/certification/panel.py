"""Minimal exact-contract panel adapter for the packaged fixture."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from .models import FixtureBar, FixtureScenario


def _frame(rows: tuple[FixtureBar, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": row.date,
                "open": row.open,
                "high": max(row.open, row.settle),
                "low": min(row.open, row.settle),
                "close": row.settle,
                "settle": row.settle,
                "volume": 1000.0,
                "open_interest": 5000.0,
                "contract": row.contract,
                "symbol": row.contract,
                "suspended": 1.0 if row.suspended else 0.0,
            }
            for row in rows
        ]
    ).set_index("date")


class CertificationPanel:
    """Read-only panel surface required by ``DailyBookBacktester``."""

    def __init__(self, scenario: FixtureScenario) -> None:
        self.snapshot_version = scenario.panel_snapshot
        self.manifest_sha256 = scenario.panel_manifest_sha256
        self.calendar = list(scenario.calendar)
        self.instruments = [row.instrument for row in scenario.instruments]
        self._main = {row.instrument: _frame(row.main_bars) for row in scenario.instruments}
        self._exact = {row.instrument: _frame(row.exact_bars) for row in scenario.instruments}
        self._meta = {row.instrument: row.meta for row in scenario.instruments}

    def view(self, date: dt.date) -> "CertificationPanelView":
        return CertificationPanelView(self, date)


class CertificationPanelView:
    def __init__(self, panel: CertificationPanel, date: dt.date) -> None:
        self._panel = panel
        self.date = date

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        frame = self._panel._main[instrument]
        return frame.loc[frame.index <= self.date].tail(lookback).copy()

    def current_bar(self, instrument: str):
        rows = self._panel._main[instrument]
        rows = rows.loc[rows.index == self.date]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar(self, instrument: str, contract: str):
        rows = self._panel._exact[instrument]
        rows = rows.loc[
            (rows.index == self.date) & (rows["contract"].astype(str) == str(contract))
        ]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar_asof(self, instrument: str, contract: str):
        rows = self._panel._exact[instrument]
        rows = rows.loc[
            (rows.index <= self.date) & (rows["contract"].astype(str) == str(contract))
        ]
        return None if rows.empty else rows.iloc[-1].copy()

    def meta(self, instrument: str):
        return self._panel._meta[instrument]
