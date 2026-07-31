"""PanelView estimates no-lookahead and shape falsifiers."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from echolon.panel.models import InstrumentMeta, PanelManifest
from echolon.panel.snapshot import ESTIMATES_COLUMNS, PanelData, PanelView


def _panel(estimates: dict[str, pd.DataFrame]) -> PanelData:
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
        estimates=estimates,
    )


def _rows() -> pd.DataFrame:
    dates = [dt.date(2020, 1, day) for day in range(1, 7)]
    return pd.DataFrame(
        {
            "consensus_eps_fy1": [float(value) for value in range(6)],
            "consensus_count": [value + 1 for value in range(6)],
            "revision_score": [value / 10.0 for value in range(6)],
            "guidance_surprise": [value / 20.0 for value in range(6)],
        },
        index=dates,
    )


def test_estimates_history_is_no_lookahead_and_tail_limited() -> None:
    panel = _panel({"000001.sz": _rows()})
    view = PanelView(panel, dt.date(2020, 1, 4))

    history = view.estimates_history("000001.SZ", 2)

    assert list(history.columns) == ESTIMATES_COLUMNS
    assert history.index.tolist() == [
        dt.date(2020, 1, 3),
        dt.date(2020, 1, 4),
    ]
    assert history["consensus_eps_fy1"].tolist() == [2.0, 3.0]
    assert dt.date(2020, 1, 5) not in history.index


def test_estimates_history_large_lookback_never_pads() -> None:
    panel = _panel({"000001.sz": _rows()})
    history = panel.view(dt.date(2020, 1, 3)).estimates_history(
        "000001.sz", 100
    )

    assert len(history) == 3
    assert history.index.max() == dt.date(2020, 1, 3)


def test_estimates_history_missing_name_is_canonical_empty() -> None:
    history = _panel({}).view(dt.date(2020, 1, 3)).estimates_history(
        "missing", 5
    )

    assert history.empty
    assert list(history.columns) == ESTIMATES_COLUMNS


def test_estimates_history_rejects_nonpositive_lookback() -> None:
    panel = _panel({"000001.sz": _rows()})

    with pytest.raises(ValueError, match="lookback must be positive"):
        panel.view(dt.date(2020, 1, 3)).estimates_history("000001.sz", -1)
