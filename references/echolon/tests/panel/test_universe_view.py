"""PanelView exact-date universe membership falsifiers."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from echolon.panel.models import InstrumentMeta, PanelManifest
from echolon.panel.snapshot import PanelData


def _panel() -> PanelData:
    dates = [dt.date(2020, 1, day) for day in range(1, 4)]
    bars = pd.DataFrame(
        {
            "open": [10.0] * 3,
            "high": [10.0] * 3,
            "low": [10.0] * 3,
            "close": [10.0] * 3,
            "settle": [10.0] * 3,
            "volume": [100.0] * 3,
            "open_interest": [0.0] * 3,
            "contract": ["000001.sz"] * 3,
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
    universe = pd.DataFrame(
        {
            "date": [dates[0], dates[0], dates[1]],
            "instrument": ["000001.sz", "000002.sz", "000002.sz"],
        }
    )
    return PanelData(
        snapshot_dir=None,
        manifest=manifest,
        bars={"000001.sz": bars},
        curves={},
        contracts={},
        meta={"000001.sz": meta},
        universe=universe,
    )


def test_universe_changes_on_exact_view_date_and_never_carries() -> None:
    panel = _panel()

    assert panel.view(dt.date(2020, 1, 1)).universe() == [
        "000001.sz",
        "000002.sz",
    ]
    assert panel.view(dt.date(2020, 1, 2)).universe() == ["000002.sz"]
    assert panel.view(dt.date(2020, 1, 3)).universe() == []


def test_universe_unknown_view_date_matches_panel_contract() -> None:
    panel = _panel()

    with pytest.raises(KeyError, match="2020-01-04"):
        panel.view(dt.date(2020, 1, 4)).universe()
