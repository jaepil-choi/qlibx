"""PanelView.curve_history no-lookahead and shape tests."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from echolon.panel.snapshot import CURVE_COLUMNS, PanelData, PanelView
from echolon.panel.models import InstrumentMeta, PanelManifest


def _panel_with_curves(curve_rows: dict[str, list[dict]]) -> PanelData:
    dates = [dt.date(2024, 1, 1) + dt.timedelta(days=index) for index in range(6)]
    bars = pd.DataFrame(
        {
            "open": [100.0] * 6,
            "high": [100.0] * 6,
            "low": [100.0] * 6,
            "close": [100.0] * 6,
            "settle": [100.0] * 6,
            "open_raw": [100.0] * 6,
            "high_raw": [100.0] * 6,
            "low_raw": [100.0] * 6,
            "close_raw": [100.0] * 6,
            "settle_raw": [100.0] * 6,
            "open_adj": [100.0] * 6,
            "high_adj": [100.0] * 6,
            "low_adj": [100.0] * 6,
            "close_adj": [100.0] * 6,
            "settle_adj": [100.0] * 6,
            "adj_factor": [1.0] * 6,
            "volume": [10] * 6,
            "open_interest": [10] * 6,
            "contract": ["c1"] * 6,
        },
        index=dates,
    )
    curves = {
        instrument: pd.DataFrame(rows, index=dates[: len(rows)])
        for instrument, rows in curve_rows.items()
    }
    meta = InstrumentMeta(
        instrument_id="al",
        sector="base_metals",
        multiplier=5.0,
        tick=5.0,
        margin_rate=0.1,
        commission=3.0,
        commission_type="per_contract",
        close_today_commission=None,
        currency="RMB",
    )
    manifest = PanelManifest(
        schema="panel/v1",
        version="test_snapshot",
        created_at="2024-01-01T00:00:00+00:00",
        source_refs=["test"],
        calendar_start=dates[0],
        calendar_end=dates[-1],
        instruments=["al"],
        files={},
        qc_report="qc_report.json",
        qc_status="PASS",
    )
    return PanelData(
        snapshot_dir=None,
        manifest=manifest,
        bars={"al": bars},
        curves=curves,
        contracts={},
        meta={"al": meta},
    )


def _curve_row(near: float, far: float, near_contract: str = "al2401") -> dict:
    return {
        "near_contract": near_contract,
        "near_settle": near,
        "far_contract": "al2405",
        "far_settle": far,
        "days_between": 30,
    }


def test_curve_history_is_no_lookahead_and_tail_limited():
    rows = [_curve_row(100.0 + index, 95.0 + index) for index in range(6)]
    panel = _panel_with_curves({"al": rows})
    view = PanelView(panel, dt.date(2024, 1, 4))

    history = view.curve_history("al", 3)

    assert list(history.columns) == CURVE_COLUMNS
    assert len(history) == 3
    assert history.index.max() <= view.date
    assert history["near_settle"].tolist() == [101.0, 102.0, 103.0]


def test_curve_history_full_lookback_never_exceeds_view_date():
    rows = [_curve_row(100.0 + index, 95.0 + index) for index in range(6)]
    panel = _panel_with_curves({"al": rows})
    view = PanelView(panel, dt.date(2024, 1, 3))

    history = view.curve_history("al", 100)

    assert len(history) == 3
    assert history.index.max() == dt.date(2024, 1, 3)


def test_curve_history_missing_instrument_returns_empty_frame():
    panel = _panel_with_curves({})
    view = PanelView(panel, dt.date(2024, 1, 4))

    history = view.curve_history("al", 5)

    assert history.empty
    assert list(history.columns) == CURVE_COLUMNS


def test_curve_history_rejects_non_positive_lookback():
    rows = [_curve_row(100.0, 95.0)]
    panel = _panel_with_curves({"al": rows})
    view = PanelView(panel, dt.date(2024, 1, 1))

    with pytest.raises(ValueError):
        view.curve_history("al", 0)
