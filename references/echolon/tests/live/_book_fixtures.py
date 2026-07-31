"""Synthetic panel-snapshot and release-bundle builders for book tests.

Everything here is synthetic: neutral instrument ids, invented prices, no
production universe or capital information (echolon is public).
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from echolon.bundle import BundleManifest, write_bundle_manifest

SELF_CONTAINED_SIGNAL = '''
from __future__ import annotations

from echolon.signals import ScoreVector, SignalEngine


class ConstantLong(SignalEngine):
    """Scores +strength for every instrument with at least one bar."""

    signal_id = "const_long_v1"
    family = "tsmom"
    data_requirements = {"bars": 1}

    def __init__(self, *, strength: float = 1.0) -> None:
        self.strength = float(strength)
        self.params = {"strength": self.strength}

    def compute(self, view) -> ScoreVector:
        scores = {}
        for instrument in view._panel.instruments:
            bars = view.bars(instrument, 1)
            scores[instrument] = None if bars.empty else self.strength
        return ScoreVector(
            signal_id=self.signal_id,
            family=self.family,
            date=view.date,
            scores=scores,
        )
'''

CONSTRUCTOR = {
    "vol_target_ann_pct": 10.0,
    "sector_caps_pct": {},
    "max_margin_utilization_pct": 60.0,
    "min_abs_score_for_position": 0.1,
    "rebalance": "W-FRI",
}


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bar(date: str, price: float, contract: str) -> dict:
    return {
        "date": date,
        "open": price,
        "high": price + 2.0,
        "low": price - 2.0,
        "close": price,
        "settle": price,
        "volume": 1000,
        "open_interest": 5000,
        "contract": contract,
    }


def build_panel_snapshot(root: Path, version: str = "panel-test-v1") -> Path:
    """Three-instrument, ten-day snapshot with non-zero volatility."""
    snapshot = root / "panel_snapshot" / version
    dates = [
        "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26",
        "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03",
    ]
    series = {
        "aa": [100.0 + 1.0 * i + (0.5 if i % 2 else -0.5) for i in range(10)],
        "bb": [200.0 - 1.5 * i + (0.7 if i % 3 else -0.7) for i in range(10)],
        "cc": [50.0 + (1.0 if i % 2 else -1.0) for i in range(10)],
    }
    for instrument, prices in series.items():
        write_csv(
            snapshot / "bars" / f"{instrument}.csv",
            [
                _bar(date, price, f"{instrument}2608")
                for date, price in zip(dates, prices)
            ],
        )
    write_csv(
        snapshot / "meta" / "instruments.csv",
        [
            {
                "instrument_id": instrument,
                "sector": "sector_a" if instrument in ("aa", "bb") else "sector_b",
                "multiplier": 10,
                "tick": 1,
                "margin_rate": 0.10,
                "commission": 3.0,
                "commission_type": "per_contract",
                "close_today_commission": "",
                "currency": "RMB",
            }
            for instrument in series
        ],
    )
    (snapshot / "qc_report.json").write_text(
        json.dumps({"schema": "qc/v1", "snapshot": version, "status": "PASS", "checks": []}),
        encoding="utf-8",
    )
    files = {}
    for rel in [
        "bars/aa.csv",
        "bars/bb.csv",
        "bars/cc.csv",
        "meta/instruments.csv",
        "qc_report.json",
    ]:
        files[rel] = _sha256(snapshot / rel)
    (snapshot / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "panel/v1",
                "version": version,
                "created_at": "2026-07-07T00:00:00+08:00",
                "source_refs": ["synthetic"],
                "calendar_start": dates[0],
                "calendar_end": dates[-1],
                "instruments": sorted(series),
                "files": files,
                "qc_report": "qc_report.json",
                "qc_status": "PASS",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return snapshot


def build_bundle(
    root: Path,
    *,
    bundle_version: str = "1.0.0",
    signal_id: str = "const_long_v1",
    family: str = "tsmom",
    signal_source: str = SELF_CONTAINED_SIGNAL,
    params: dict | None = None,
    constructor: dict | None = None,
    risk: dict | None = None,
) -> Path:
    """Write a minimal-but-valid S5 bundle and stamp its manifest."""
    bundle_dir = root / "bundles" / bundle_version
    (bundle_dir / "signals").mkdir(parents=True)
    (bundle_dir / "params").mkdir()
    (bundle_dir / "gates").mkdir()
    (bundle_dir / "signals" / f"{signal_id}.py").write_text(signal_source, encoding="utf-8")
    (bundle_dir / "params" / f"{signal_id}.json").write_text(
        json.dumps(params if params is not None else {"strength": 1.0}),
        encoding="utf-8",
    )
    (bundle_dir / "gates" / f"{signal_id}.json").write_text(
        json.dumps({"verdict": "ADMITTED"}), encoding="utf-8"
    )
    (bundle_dir / "expectations.json").write_text(
        json.dumps(
            {
                "schema": "expectations/v1",
                "campaign_id": "camp_test",
                "panel_snapshot": "panel-test-v1",
                "metrics": {},
            }
        ),
        encoding="utf-8",
    )
    manifest = BundleManifest(
        bundle_version=bundle_version,
        echolon_version="0.2.0",
        panel_snapshot={"version": "panel-test-v1", "manifest_sha256": "a" * 64},
        signals=[
            {
                "signal_id": signal_id,
                "family": family,
                "file": f"signals/{signal_id}.py",
                "sha256": "",
                "params_file": f"params/{signal_id}.json",
                "gate_record": f"gates/{signal_id}.json",
            }
        ],
        blend={signal_id: 1.0},
        constructor=constructor if constructor is not None else dict(CONSTRUCTOR),
        risk=risk if risk is not None else {"max_drawdown_pct_of_equity": 8.0},
        expectations="expectations.json",
        provenance={
            "campaign_id": "camp_test",
            "pass_bar_sha256": "b" * 64,
            "ledger_extract": "gates/const_long_v1.json",
            "battery_verdicts": "gates/const_long_v1.json",
        },
        approval={"approved_by": "owner", "date": "2026-07-08", "note": "synthetic test bundle"},
    )
    write_bundle_manifest(bundle_dir, manifest)
    return bundle_dir
