from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
import pandas as pd

from echolon.panel import PanelData


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_snapshot(tmp_path: Path) -> Path:
    root = tmp_path / "panel_snapshot" / "v-test"
    _write_csv(
        root / "bars" / "al.csv",
        [
            {
                "date": "2024-01-02",
                "open": 19000,
                "high": 19100,
                "low": 18900,
                "close": 19010,
                "settle": 19008,
                "volume": 1000,
                "open_interest": 10000,
                "contract": "al2402",
            },
            {
                "date": "2024-01-03",
                "open": 19010,
                "high": 19110,
                "low": 18910,
                "close": 19020,
                "settle": 19018,
                "volume": 1100,
                "open_interest": 10010,
                "contract": "al2402",
            },
            {
                "date": "2024-01-04",
                "open": 19020,
                "high": 19120,
                "low": 18920,
                "close": 19030,
                "settle": 19028,
                "volume": 1200,
                "open_interest": 10020,
                "contract": "al2402",
            },
        ],
    )
    _write_csv(
        root / "bars" / "cu.csv",
        [
            {
                "date": "2024-01-02",
                "open": 70000,
                "high": 70100,
                "low": 69900,
                "close": 70000,
                "settle": 70000,
                "volume": 2000,
                "open_interest": 20000,
                "contract": "cu2402",
            },
            {
                "date": "2024-01-03",
                "open": 70000,
                "high": 70100,
                "low": 69900,
                "close": 70010,
                "settle": 70008,
                "volume": 2100,
                "open_interest": 20010,
                "contract": "cu2402",
            },
        ],
    )
    _write_csv(
        root / "curves" / "al.csv",
        [
            {
                "date": "2024-01-03",
                "near_contract": "al2402",
                "near_settle": 19018,
                "far_contract": "al2403",
                "far_settle": 19088,
                "days_between": 30,
            }
        ],
    )
    _write_csv(
        root / "meta" / "instruments.csv",
        [
            {
                "instrument_id": "al",
                "sector": "base_metals",
                "multiplier": 5,
                "tick": 5,
                "margin_rate": 0.09,
                "commission": 3.01,
                "commission_type": "per_contract",
                "close_today_commission": "",
                "currency": "RMB",
            },
            {
                "instrument_id": "cu",
                "sector": "base_metals",
                "multiplier": 5,
                "tick": 10,
                "margin_rate": 0.09,
                "commission": 0.00005,
                "commission_type": "percentage",
                "close_today_commission": "",
                "currency": "RMB",
            },
        ],
    )
    (root / "qc_report.json").write_text(
        json.dumps({"schema": "qc/v1", "snapshot": "v-test", "status": "PASS", "checks": []}),
        encoding="utf-8",
    )

    files = {}
    for rel in [
        "bars/al.csv",
        "bars/cu.csv",
        "curves/al.csv",
        "meta/instruments.csv",
        "qc_report.json",
    ]:
        files[rel] = _sha256(root / rel)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "panel/v1",
                "version": "v-test",
                "created_at": "2026-07-07T00:00:00+08:00",
                "source_refs": ["synthetic"],
                "calendar_start": "2024-01-02",
                "calendar_end": "2024-01-04",
                "instruments": ["al", "cu"],
                "files": files,
                "qc_report": "qc_report.json",
                "qc_status": "PASS",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return root


def test_panel_data_loads_snapshot_and_exposes_calendar(tmp_path):
    snapshot = _build_snapshot(tmp_path)

    panel = PanelData.load(snapshot)

    assert panel.snapshot_version == "v-test"
    assert panel.instruments == ["al", "cu"]
    assert [day.isoformat() for day in panel.calendar] == [
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
    ]
    assert panel._sector_membership.empty


def test_panel_view_bars_are_no_lookahead_and_lookback_limited(tmp_path):
    panel = PanelData.load(_build_snapshot(tmp_path))

    view = panel.view("2024-01-03")
    bars = view.bars("al", lookback=1)

    assert list(bars.index.astype(str)) == ["2024-01-03"]
    assert bars.iloc[-1]["close"] == 19020


def test_panel_view_current_bar_requires_an_exact_instrument_session(tmp_path):
    panel = PanelData.load(_build_snapshot(tmp_path))
    view = panel.view("2024-01-04")

    assert view.current_bar("al") is not None
    assert view.current_bar("al").name.isoformat() == "2024-01-04"
    assert view.current_bar("cu") is None
    assert view.bars("cu", lookback=1).iloc[-1].name.isoformat() == "2024-01-03"


def test_panel_view_contract_bar_asof_never_substitutes_another_contract(tmp_path):
    panel = PanelData.load(_build_snapshot(tmp_path))
    view = panel.view("2024-01-04")

    held = view.contract_bar_asof("cu", "cu2402")
    assert held is not None
    assert held.name.isoformat() == "2024-01-03"
    assert view.contract_bar_asof("cu", "cu9999") is None


def test_panel_view_metadata_is_immutable_and_matches_panel(tmp_path):
    panel = PanelData.load(_build_snapshot(tmp_path))
    view = panel.view("2024-01-03")

    assert view.instruments == tuple(panel.instruments) == ("al", "cu")
    assert view.calendar == tuple(panel.calendar)
    assert view.snapshot_version == panel.snapshot_version == "v-test"
    assert view.date_index == 1
    with pytest.raises(TypeError):
        view.instruments[0] = "changed"
    with pytest.raises(TypeError):
        view.calendar[0] = view.calendar[-1]


@pytest.mark.parametrize(
    ("mutation", "attribute", "match"),
    [
        (lambda panel: panel.instruments.append("AL"), "instruments", "unique normalized"),
        (lambda panel: panel.calendar.append(panel.calendar[-1]), "calendar", "strictly increasing"),
        (lambda panel: setattr(panel, "snapshot_version", "other"), "snapshot_version", "inconsistent"),
    ],
)
def test_panel_view_metadata_fails_loudly_on_inconsistent_panel(
    tmp_path, mutation, attribute, match
):
    panel = PanelData.load(_build_snapshot(tmp_path))
    view = panel.view("2024-01-03")
    mutation(panel)

    with pytest.raises(ValueError, match=match):
        getattr(view, attribute)


def test_panel_view_rejects_dates_outside_calendar(tmp_path):
    panel = PanelData.load(_build_snapshot(tmp_path))

    with pytest.raises(KeyError, match="2024-01-05"):
        panel.view("2024-01-05")


def test_panel_view_curve_and_meta(tmp_path):
    panel = PanelData.load(_build_snapshot(tmp_path))
    view = panel.view("2024-01-03")

    curve = view.curve("al")
    assert curve is not None
    assert curve.near_contract == "al2402"
    assert curve.far_contract == "al2403"
    assert curve.days_between == 30
    assert view.curve("cu") is None

    meta = view.meta("al")
    assert meta.instrument_id == "al"
    assert meta.sector == "base_metals"
    assert meta.close_today_commission is None


def test_panel_data_rejects_manifest_hash_mismatch(tmp_path):
    snapshot = _build_snapshot(tmp_path)
    with open(snapshot / "bars" / "al.csv", "a", encoding="utf-8") as f:
        f.write("\n")

    with pytest.raises(ValueError, match="hash mismatch"):
        PanelData.load(snapshot)
def test_legacy_bar_frame_defaults_equity_tradability_columns():
    from echolon.panel.snapshot import _normalize_bar_frame

    frame = pd.DataFrame(
        {name: [10.0] for name in ("open", "high", "low", "close", "settle")}
    )
    normalized = _normalize_bar_frame(frame)

    assert normalized.loc[0, "suspended"] == 0.0
    assert pd.isna(normalized.loc[0, "limit_up_price"])
    assert pd.isna(normalized.loc[0, "limit_down_price"])


def test_instrument_meta_equity_fields_default_to_futures_behavior():
    from echolon.panel.models import InstrumentMeta

    meta = InstrumentMeta(
        instrument_id="al", sector="base", multiplier=5.0, tick=5.0,
        margin_rate=0.1, commission=3.0, commission_type="per_contract",
    )
    assert meta.min_order_size == 1.0
    assert meta.t_plus_one is False
    assert meta.stamp_duty_rate == 0.0
    assert meta.transfer_fee_rate == 0.0
    assert meta.min_commission == 0.0
