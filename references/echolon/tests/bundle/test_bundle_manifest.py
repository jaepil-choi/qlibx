from __future__ import annotations

import json

import pytest

from echolon.bundle import BundleManifest, load_bundle, write_bundle_manifest
from echolon.bundle.cli import main as bundle_cli_main


def test_bundle_manifest_round_trip_and_hash_verification(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "signals").mkdir()
    (bundle_dir / "signals" / "tsmom_v1.py").write_text("SIGNAL = 'tsmom_v1'\n", encoding="utf-8")
    (bundle_dir / "params.json").write_text('{"lookback": 252}\n', encoding="utf-8")
    (bundle_dir / "expectations.json").write_text('{"schema": "expectations/v1"}\n', encoding="utf-8")

    manifest = BundleManifest(
        bundle_version="0.1.0",
        echolon_version="0.2.0",
        panel_snapshot={"version": "p2_v1", "manifest_sha256": "a" * 64},
        signals=[
            {
                "signal_id": "tsmom_v1",
                "family": "tsmom",
                "file": "signals/tsmom_v1.py",
                "sha256": "",
                "params_file": "params.json",
                "gate_record": "gate.json",
            }
        ],
        blend={"tsmom_v1": 1.0},
        constructor={
            "vol_target_ann_pct": 10.0,
            "sector_caps_pct": {"base": 25.0},
            "max_margin_utilization_pct": 40.0,
            "min_abs_score_for_position": 0.5,
            "rebalance": "W-FRI",
        },
        risk={"max_drawdown_pct_of_equity": 8.0},
        expectations="expectations.json",
        provenance={
            "campaign_id": "camp_1",
            "pass_bar_sha256": "b" * 64,
            "ledger_extract": "ledger.json",
            "battery_verdicts": "battery.json",
        },
        approval={"approved_by": "owner", "date": "2026-07-07", "note": "test"},
    )

    written = write_bundle_manifest(bundle_dir, manifest)
    loaded = load_bundle(bundle_dir)

    assert loaded.bundle_version == written.bundle_version
    assert loaded.files == {
        "expectations.json": loaded.files["expectations.json"],
        "params.json": loaded.files["params.json"],
        "signals/tsmom_v1.py": loaded.files["signals/tsmom_v1.py"],
    }
    assert loaded.signals[0].sha256 == loaded.files["signals/tsmom_v1.py"]


def test_bundle_loader_refuses_hash_mismatch(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "signal.py").write_text("x = 1\n", encoding="utf-8")
    manifest = BundleManifest(
        bundle_version="0.1.0",
        echolon_version="0.2.0",
        panel_snapshot={"version": "p2_v1", "manifest_sha256": "a" * 64},
        signals=[
            {
                "signal_id": "sig",
                "family": "carry",
                "file": "signal.py",
                "sha256": "",
                "params_file": "params.json",
                "gate_record": "gate.json",
            }
        ],
        blend={"sig": 1.0},
        constructor={
            "vol_target_ann_pct": 10.0,
            "sector_caps_pct": {},
            "max_margin_utilization_pct": 40.0,
            "min_abs_score_for_position": 0.5,
            "rebalance": "W-FRI",
        },
        risk={"max_drawdown_pct_of_equity": 8.0},
        expectations="expectations.json",
        provenance={
            "campaign_id": "camp_1",
            "pass_bar_sha256": "b" * 64,
            "ledger_extract": "ledger.json",
            "battery_verdicts": "battery.json",
        },
        approval={"approved_by": "owner", "date": "2026-07-07", "note": "test"},
    )
    write_bundle_manifest(bundle_dir, manifest)
    (bundle_dir / "signal.py").write_text("x = 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        load_bundle(bundle_dir)


def test_bundle_manifest_requires_blend_weights_sum_to_one(tmp_path):
    payload = {
        "schema": "bundle/v1",
        "bundle_version": "0.1.0",
        "created_at": "2026-07-07T00:00:00Z",
        "echolon_version": "0.2.0",
        "panel_snapshot": {"version": "p2_v1", "manifest_sha256": "a" * 64},
        "signals": [],
        "blend": {"a": 0.2, "b": 0.2},
        "constructor": {
            "vol_target_ann_pct": 10.0,
            "sector_caps_pct": {},
            "max_margin_utilization_pct": 40.0,
            "min_abs_score_for_position": 0.5,
            "rebalance": "W-FRI",
        },
        "risk": {"max_drawdown_pct_of_equity": 8.0},
        "expectations": "expectations.json",
        "provenance": {
            "campaign_id": "camp_1",
            "pass_bar_sha256": "b" * 64,
            "ledger_extract": "ledger.json",
            "battery_verdicts": "battery.json",
        },
        "approval": {"approved_by": "owner", "date": "2026-07-07", "note": "test"},
        "files": {},
    }

    with pytest.raises(ValueError, match="blend weights"):
        BundleManifest.model_validate_json(json.dumps(payload))


def test_bundle_verify_cli_returns_zero_for_valid_bundle(tmp_path, capsys):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "signal.py").write_text("x = 1\n", encoding="utf-8")
    manifest = BundleManifest(
        bundle_version="0.1.0",
        echolon_version="0.2.0",
        panel_snapshot={"version": "p2_v1", "manifest_sha256": "a" * 64},
        signals=[
            {
                "signal_id": "sig",
                "family": "carry",
                "file": "signal.py",
                "sha256": "",
                "params_file": "params.json",
                "gate_record": "gate.json",
            }
        ],
        blend={"sig": 1.0},
        constructor={
            "vol_target_ann_pct": 10.0,
            "sector_caps_pct": {},
            "max_margin_utilization_pct": 40.0,
            "min_abs_score_for_position": 0.5,
            "rebalance": "W-FRI",
        },
        risk={"max_drawdown_pct_of_equity": 8.0},
        expectations="expectations.json",
        provenance={
            "campaign_id": "camp_1",
            "pass_bar_sha256": "b" * 64,
            "ledger_extract": "ledger.json",
            "battery_verdicts": "battery.json",
        },
        approval={"approved_by": "owner", "date": "2026-07-07", "note": "test"},
    )
    write_bundle_manifest(bundle_dir, manifest)

    assert bundle_cli_main(["verify", str(bundle_dir)]) == 0
    assert "bundle verified" in capsys.readouterr().out
