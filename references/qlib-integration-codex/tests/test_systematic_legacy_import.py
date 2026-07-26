from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from qlib_extended.research import LegacyResearchImporter, rebuild_catalog


def test_importer_registers_every_ledger_row_and_selected_weight(tmp_path: Path) -> None:
    research_root = tmp_path / "research"
    _write_ledger_fixture(research_root)
    _write_selected_fixture(research_root)
    artifact_root = research_root / "artifacts"
    catalog_path = research_root / "alpha_pool.duckdb"
    summary_path = research_root / "legacy_import_summary.json"
    importer = LegacyResearchImporter(research_root, artifact_root, catalog_path)

    summary = importer.import_all(summary_path=summary_path)

    assert summary.ledger_files == 2
    assert summary.ledger_rows == 3
    assert summary.selected_manifests == 1
    assert summary.selected_runs == 3
    assert summary.published_runs == 6
    assert summary.catalog_runs == 6
    assert summary.catalog_members == 2
    assert summary.source_rows == {
        "ensemble/outputs/trial_ledger.csv": 1,
        "price/results/trial_ledger.csv": 2,
    }
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["catalog_runs"] == 6

    rebuilt = rebuild_catalog(catalog_path, artifact_root)
    assert len(rebuilt.runs()) == 6
    assert set(rebuilt.runs()["research_track"]) == {"legacy"}
    assert set(rebuilt.runs()["status"]) == {"complete", "failed"}
    assert len(rebuilt.members()) == 2
    assert "validation" in set(rebuilt.metrics()["segment"])


def test_importer_is_idempotent(tmp_path: Path) -> None:
    research_root = tmp_path / "research"
    _write_ledger_fixture(research_root)
    _write_selected_fixture(research_root)
    importer = LegacyResearchImporter(
        research_root,
        research_root / "artifacts",
        research_root / "alpha_pool.duckdb",
    )

    first = importer.import_all()
    second = importer.import_all()

    assert first.catalog_runs == second.catalog_runs == 6
    assert first.catalog_metrics == second.catalog_metrics


def test_importer_rejects_missing_selected_parquet(tmp_path: Path) -> None:
    research_root = tmp_path / "research"
    _write_ledger_fixture(research_root)
    _write_selected_fixture(research_root)
    missing = research_root / "price" / "weights" / "member_b.parquet"
    missing.unlink()
    importer = LegacyResearchImporter(
        research_root,
        research_root / "artifacts",
        research_root / "alpha_pool.duckdb",
    )

    with pytest.raises(FileNotFoundError, match="Selected weight artifact is missing"):
        importer.import_all()


def _write_ledger_fixture(research_root: Path) -> None:
    price = research_root / "price" / "results"
    ensemble = research_root / "ensemble" / "outputs"
    price.mkdir(parents=True)
    ensemble.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "trial_id": "price_a",
                "status": "complete",
                "rebalance_interval": 21,
                "order_calendar_key": "common_21d",
                "development_gross_return": 0.01,
                "validation_gross_return": 0.02,
            },
            {
                "trial_id": "price_b",
                "status": "failed",
                "failure_reason": "schema mismatch",
                "rebalance_interval": 5,
            },
        ]
    ).to_csv(price / "trial_ledger.csv", index=False)
    pd.DataFrame(
        [
            {
                "candidate": "physical_a",
                "status": "complete",
                "full_net_active_return": 0.003,
                "annualized_trade_cost": 0.004,
            }
        ]
    ).to_csv(ensemble / "trial_ledger.csv", index=False)


def _write_selected_fixture(research_root: Path) -> None:
    price = research_root / "price"
    weights = price / "weights"
    weights.mkdir(parents=True)
    frame = pd.DataFrame(
        {"A": [0.1, 0.2], "B": [-0.1, -0.2]},
        index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="date"),
    )
    frame.to_parquet(weights / "member_a.parquet")
    frame.to_parquet(weights / "member_b.parquet")
    frame.to_parquet(weights / "family.parquet")
    payload = {
        "schema_version": 1,
        "candidates": [
            {
                "name": "member_a",
                "path": "weights/member_a.parquet",
                "frequency_days": 21,
                "order_calendar_key": "common_21d",
                "validation_gross_return": 0.01,
            },
            {
                "name": "member_b",
                "path": "weights/member_b.parquet",
                "frequency_days": 21,
                "order_calendar_key": "common_21d",
                "validation_gross_return": 0.02,
            },
        ],
        "frequency_ensembles": [
            {
                "name": "family",
                "path": "weights/family.parquet",
                "frequency_days": 21,
                "order_calendar_key": "common_21d",
                "members": ["member_a", "member_b"],
                "member_weight": 0.5,
                "annualized_net_return": 0.03,
            }
        ],
    }
    (price / "selected_candidates.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
