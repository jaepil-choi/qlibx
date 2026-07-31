"""On-disk equity snapshot plumbing tests."""
from __future__ import annotations

import hashlib
import json

import pandas as pd

from echolon.panel.snapshot import BAR_COLUMNS, PanelData


def test_load_optional_equity_families_and_metadata(tmp_path) -> None:
    instrument = "000001.sz"
    files = {
        f"bars/{instrument}.csv": pd.DataFrame(
            {
                "date": ["2020-01-02"],
                "open": [10.0],
                "high": [10.0],
                "low": [10.0],
                "close": [10.0],
                "settle": [10.0],
                "volume": [100.0],
                "open_interest": [0.0],
                "contract": [instrument],
            }
        ),
        f"fundamentals/{instrument}.csv": pd.DataFrame(
            {
                "date": ["2020-01-02"],
                "report_period": ["20191231"],
                "ann_date": ["20200102"],
                "net_profit_q": [1.0],
                "revenue_q": [2.0],
                "total_equity": [3.0],
                "total_assets": [4.0],
                "ocf_q": [5.0],
                "net_profit_ttm": [6.0],
                "revenue_ttm": [7.0],
                "ocf_ttm": [8.0],
            }
        ),
        f"estimates/{instrument}.csv": pd.DataFrame(
            {
                "date": ["2020-01-02"],
                "consensus_eps_fy1": [1.0],
                "consensus_count": [2.0],
                "revision_score": [0.1],
                "guidance_surprise": [0.2],
            }
        ),
        "universe/membership.csv": pd.DataFrame(
            {"date": ["2020-01-02"], "instrument": [instrument]}
        ),
        "universe/sw_membership.csv": pd.DataFrame(
            {
                "instrument": [instrument],
                "l1_code": ["801780"],
                "in_date": ["20190101"],
                "out_date": [None],
            }
        ),
        "meta/instruments.csv": pd.DataFrame(
            {
                "instrument_id": [instrument],
                "sector": ["801780"],
                "multiplier": [1.0],
                "tick": [0.01],
                "margin_rate": [1.0],
                "commission": [0.0003],
                "commission_type": ["notional"],
                "close_today_commission": [None],
                "currency": ["RMB"],
                "min_order_size": [100.0],
                "t_plus_one": [True],
                "stamp_duty_rate": [0.0005],
                "transfer_fee_rate": [0.00001],
                "min_commission": [5.0],
            }
        ),
    }
    hashes = {}
    for relpath, frame in files.items():
        path = tmp_path / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
        hashes[relpath] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "schema": "panel/v1",
        "version": "equity-test",
        "created_at": "2020-01-02T00:00:00+00:00",
        "source_refs": ["fixture"],
        "calendar_start": "2020-01-02",
        "calendar_end": "2020-01-02",
        "instruments": [instrument],
        "files": hashes,
        "qc_report": "qc_report.json",
        "qc_status": "PASS_WITH_WARNINGS",
        "adjustment_convention": "hfq_asof",
        "pit_status": "ann_date_approx",
        "selection_date": "2018-06-29",
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    panel = PanelData.load(tmp_path)
    view = panel.view("2020-01-02")

    assert list(view.bars(instrument, 1).columns) == BAR_COLUMNS
    assert pd.isna(view.bars(instrument, 1)["amount"].item())
    assert view.bars(instrument, 1)["suspended"].item() == 0.0
    assert view.fundamentals_history(instrument, 1)["net_profit_q"].item() == 1.0
    assert view.estimates_history(instrument, 1)["guidance_surprise"].item() == 0.2
    assert view.universe() == [instrument]
    assert view.sector_asof(instrument) == "801780"
    assert view.meta(instrument).min_order_size == 100.0
    assert view.meta(instrument).t_plus_one is True
    assert view.meta(instrument).stamp_duty_rate == 0.0005
    assert view.meta(instrument).transfer_fee_rate == 0.00001
    assert view.meta(instrument).min_commission == 5.0
    assert panel.manifest.adjustment_convention == "hfq_asof"
    assert panel.manifest.pit_status == "ann_date_approx"
    assert panel.manifest.selection_date.isoformat() == "2018-06-29"
