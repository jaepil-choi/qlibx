"""PanelView fundamentals no-lookahead and shape falsifiers."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from echolon.panel.models import InstrumentMeta, PanelManifest
from echolon.panel.snapshot import (
    FUNDAMENTALS_COLUMNS,
    PanelData,
    PanelView,
)


def _panel(fundamentals: dict[str, pd.DataFrame]) -> PanelData:
    dates = [dt.date(2020, 1, day) for day in range(1, 7)]
    bars = pd.DataFrame(
        {
            "open": [10.0] * 6,
            "high": [10.0] * 6,
            "low": [10.0] * 6,
            "close": [10.0] * 6,
            "settle": [10.0] * 6,
            "volume": [100.0] * 6,
            "open_interest": [0.0] * 6,
            "contract": ["000001.sz"] * 6,
        },
        index=dates,
    )
    manifest = PanelManifest(
        version="test",
        created_at="2020-01-01T00:00:00+00:00",
        source_refs=["fixture"],
        calendar_start=dates[0],
        calendar_end=dates[-1],
        instruments=["000001.sz"],
        files={},
        qc_report="qc_report.json",
        qc_status="PASS",
    )
    meta = InstrumentMeta(
        instrument_id="000001.sz",
        sector="801780",
        multiplier=1.0,
        tick=0.01,
        margin_rate=1.0,
        commission=0.0,
        commission_type="notional",
    )
    return PanelData(
        snapshot_dir=None,
        manifest=manifest,
        bars={"000001.sz": bars},
        curves={},
        contracts={},
        meta={"000001.sz": meta},
        fundamentals=fundamentals,
    )


def _rows() -> pd.DataFrame:
    dates = [dt.date(2020, 1, day) for day in range(1, 7)]
    rows = []
    for value in range(6):
        rows.append(
            {
                "report_period": "20191231",
                "ann_date": dates[value].isoformat(),
                "net_profit_q": float(value),
                "revenue_q": 10.0,
                "total_equity": 20.0,
                "total_assets": 30.0,
                "ocf_q": 4.0,
                "net_profit_ttm": 5.0,
                "revenue_ttm": 40.0,
                "ocf_ttm": 6.0,
            }
        )
    return pd.DataFrame(rows, index=dates)


def test_fundamentals_history_is_no_lookahead_and_tail_limited() -> None:
    panel = _panel({"000001.sz": _rows()})
    view = PanelView(panel, dt.date(2020, 1, 4))

    history = view.fundamentals_history("000001.SZ", 3)

    assert list(history.columns) == FUNDAMENTALS_COLUMNS
    assert history.index.tolist() == [
        dt.date(2020, 1, 2),
        dt.date(2020, 1, 3),
        dt.date(2020, 1, 4),
    ]
    assert history["net_profit_q"].tolist() == [1.0, 2.0, 3.0]
    assert dt.date(2020, 1, 5) not in history.index


def test_fundamentals_history_large_lookback_never_pads() -> None:
    panel = _panel({"000001.sz": _rows()})
    history = panel.view(dt.date(2020, 1, 3)).fundamentals_history(
        "000001.sz", 100
    )

    assert len(history) == 3
    assert history.index.max() == dt.date(2020, 1, 3)


def test_fundamentals_history_missing_name_is_canonical_empty() -> None:
    history = _panel({}).view(dt.date(2020, 1, 3)).fundamentals_history(
        "missing", 5
    )

    assert history.empty
    assert list(history.columns) == FUNDAMENTALS_COLUMNS


def test_fundamentals_history_rejects_nonpositive_lookback() -> None:
    panel = _panel({"000001.sz": _rows()})

    with pytest.raises(ValueError, match="lookback must be positive"):
        panel.view(dt.date(2020, 1, 3)).fundamentals_history("000001.sz", 0)
