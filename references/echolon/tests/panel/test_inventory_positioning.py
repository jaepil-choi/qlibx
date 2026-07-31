"""Panel v3 inventory and positioning load/view contracts."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from echolon.panel import PanelData


INVENTORY_COLUMNS = ["receipts", "receipts_chg", "unit"]
POSITIONING_COLUMNS = ["long_oi_top20", "short_oi_top20", "net_share"]


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(tmp_path: Path, *, schema: str = "panel/v3", include_v3: bool = True) -> Path:
    root = tmp_path / "snapshot"
    _write_csv(
        root / "bars" / "al.csv",
        [
            {"date": "2024-01-02", "open": 10, "high": 11, "low": 9, "close": 10, "settle": 10, "volume": 1, "open_interest": 2, "contract": "al2402"},
            {"date": "2024-01-03", "open": 11, "high": 12, "low": 10, "close": 11, "settle": 11, "volume": 1, "open_interest": 2, "contract": "al2402"},
            {"date": "2024-01-04", "open": 12, "high": 13, "low": 11, "close": 12, "settle": 12, "volume": 1, "open_interest": 2, "contract": "al2402"},
        ],
    )
    _write_csv(
        root / "meta" / "instruments.csv",
        [{"instrument_id": "al", "sector": "base_metals", "multiplier": 5, "tick": 5, "margin_rate": 0.09, "commission": 3, "commission_type": "per_contract", "close_today_commission": "", "currency": "RMB"}],
    )
    (root / "qc_report.json").write_text(
        json.dumps({"schema": "qc/v1", "snapshot": "test", "status": "PASS", "checks": []}),
        encoding="utf-8",
    )
    files = {
        rel: _sha256(root / rel)
        for rel in ("bars/al.csv", "meta/instruments.csv", "qc_report.json")
    }
    if include_v3:
        _write_csv(
            root / "inventory" / "al.csv",
            [
                {"date": "2024-01-02", "receipts": 100, "receipts_chg": None, "unit": "ton"},
                {"date": "2024-01-03", "receipts": 125, "receipts_chg": 25, "unit": "ton"},
                {"date": "2024-01-04", "receipts": 120, "receipts_chg": -5, "unit": "ton"},
            ],
        )
        _write_csv(
            root / "positioning" / "al.csv",
            [
                {"date": "2024-01-02", "long_oi_top20": 60, "short_oi_top20": 40, "net_share": 0.2},
                {"date": "2024-01-03", "long_oi_top20": 55, "short_oi_top20": 45, "net_share": 0.1},
                {"date": "2024-01-04", "long_oi_top20": 40, "short_oi_top20": 60, "net_share": -0.2},
            ],
        )
        files["inventory/al.csv"] = _sha256(root / "inventory" / "al.csv")
        files["positioning/al.csv"] = _sha256(root / "positioning" / "al.csv")
    (root / "manifest.json").write_text(
        json.dumps({
            "schema": schema,
            "version": "test",
            "created_at": "2026-07-12T00:00:00Z",
            "source_refs": ["synthetic"],
            "calendar_start": "2024-01-02",
            "calendar_end": "2024-01-04",
            "instruments": ["al"],
            "files": files,
            "qc_report": "qc_report.json",
            "qc_status": "PASS",
        }),
        encoding="utf-8",
    )
    return root


@pytest.mark.parametrize(
    ("method", "expected_columns", "expected_last"),
    [
        ("inventory_history", INVENTORY_COLUMNS, 125),
        ("positioning_history", POSITIONING_COLUMNS, 55),
    ],
)
def test_panel_v3_histories_are_no_lookahead_tail_limited_copies(
    tmp_path, method, expected_columns, expected_last
):
    view = PanelData.load(_snapshot(tmp_path)).view("2024-01-03")

    history = getattr(view, method)("AL", 1)

    assert list(history.index.astype(str)) == ["2024-01-03"]
    assert list(history.columns) == expected_columns
    assert history.iloc[-1, 0] == expected_last
    history.iloc[-1, 0] = -999
    assert getattr(view, method)("al", 1).iloc[-1, 0] == expected_last


@pytest.mark.parametrize("method", ["inventory_history", "positioning_history"])
def test_panel_v3_histories_missing_instrument_return_canonical_empty_frame(tmp_path, method):
    view = PanelData.load(_snapshot(tmp_path)).view("2024-01-03")

    result = getattr(view, method)("cu", 5)

    expected = INVENTORY_COLUMNS if method == "inventory_history" else POSITIONING_COLUMNS
    assert result.empty
    assert list(result.columns) == expected


@pytest.mark.parametrize("method", ["inventory_history", "positioning_history"])
@pytest.mark.parametrize("lookback", [0, -1])
def test_panel_v3_histories_reject_non_positive_lookback(tmp_path, method, lookback):
    view = PanelData.load(_snapshot(tmp_path)).view("2024-01-03")

    with pytest.raises(ValueError, match="lookback must be positive"):
        getattr(view, method)("al", lookback)


def test_panel_v1_snapshot_remains_loadable_with_empty_v3_histories(tmp_path):
    panel = PanelData.load(_snapshot(tmp_path, schema="panel/v1", include_v3=False))

    assert panel.view("2024-01-03").inventory_history("al", 5).empty
    assert panel.view("2024-01-03").positioning_history("al", 5).empty


def test_panel_load_ignores_unmanifested_optional_v3_file(tmp_path):
    snapshot = _snapshot(tmp_path, schema="panel/v1", include_v3=False)
    _write_csv(
        snapshot / "inventory" / "al.csv",
        [{"date": "2024-01-03", "receipts": 999, "receipts_chg": 999, "unit": "ton"}],
    )

    assert PanelData.load(snapshot).view("2024-01-03").inventory_history("al", 5).empty


def test_panel_v3_zero_denominator_net_share_remains_missing(tmp_path):
    snapshot = _snapshot(tmp_path)
    frame = pd.read_csv(snapshot / "positioning" / "al.csv")
    frame.loc[1, ["long_oi_top20", "short_oi_top20", "net_share"]] = [0, 0, None]
    frame.to_csv(snapshot / "positioning" / "al.csv", index=False)
    payload = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    payload["files"]["positioning/al.csv"] = _sha256(snapshot / "positioning" / "al.csv")
    (snapshot / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    value = PanelData.load(snapshot).view("2024-01-03").positioning_history("al", 1).iloc[0]["net_share"]

    assert pd.isna(value)
