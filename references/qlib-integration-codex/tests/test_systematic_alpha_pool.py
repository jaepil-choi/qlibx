from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from qlib_extended.research import (
    AlphaPoolCatalog,
    ImmutableArtifactStore,
    MemberWeight,
    MetricValue,
    RunSpec,
    rebuild_catalog,
)


def test_worker_publication_does_not_write_catalog(tmp_path: Path) -> None:
    store = ImmutableArtifactStore(tmp_path / "artifacts")
    spec = _spec("market.momentum")

    run_dir = store.publish(
        spec,
        metrics=[MetricValue("validation", "gross_return", 0.02)],
        frames={"target_weights": _frame()},
        provenance={"resolved_config": {"lookback": 21}},
    )

    assert run_dir == (tmp_path / "artifacts" / spec.run_id).resolve()
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "target_weights.parquet").is_file()
    assert not (tmp_path / "alpha_pool.duckdb").exists()


def test_catalog_has_only_three_core_tables_and_registers_manifest(tmp_path: Path) -> None:
    store = ImmutableArtifactStore(tmp_path / "artifacts")
    spec = _spec("market.reversal")
    run_dir = store.publish(
        spec,
        metrics=[
            MetricValue("development", "gross_return", 0.01),
            MetricValue("validation", "gross_return", 0.02),
        ],
        frames={"signal": _frame()},
    )
    catalog = AlphaPoolCatalog(tmp_path / "alpha_pool.duckdb")

    run_id = catalog.register_manifest(run_dir / "manifest.json")

    assert run_id == spec.run_id
    assert catalog.runs()["run_id"].tolist() == [spec.run_id]
    assert len(catalog.metrics()) == 2
    assert catalog.members().empty
    with duckdb.connect(str(catalog.path), read_only=True) as connection:
        assert {row[0] for row in connection.execute("show tables").fetchall()} == {
            "members",
            "metrics",
            "runs",
        }


def test_artifact_publication_is_idempotent_but_immutable(tmp_path: Path) -> None:
    store = ImmutableArtifactStore(tmp_path / "artifacts")
    spec = _spec("market.volume")
    first = store.publish(spec, frames={"signal": _frame()})
    second = store.publish(spec, frames={"signal": _frame()})

    assert first == second
    changed = _frame().copy()
    changed.iloc[0, 0] = 99.0
    with pytest.raises(ValueError, match="Immutable run collision"):
        store.publish(spec, frames={"signal": changed})


def test_failed_trial_is_registered_without_matrix_artifacts(tmp_path: Path) -> None:
    store = ImmutableArtifactStore(tmp_path / "artifacts")
    spec = _spec("consensus.failed", status="failed", attempt=1)
    run_dir = store.publish(spec, provenance={"failure_reason": "missing field"})
    catalog = AlphaPoolCatalog(tmp_path / "alpha_pool.duckdb")

    catalog.register_manifest(run_dir / "manifest.json")

    row = catalog.runs().iloc[0]
    assert row["status"] == "failed"
    assert catalog.metrics().empty


def test_ensemble_registration_requires_registered_members(tmp_path: Path) -> None:
    store = ImmutableArtifactStore(tmp_path / "artifacts")
    missing = _spec("market.missing")
    ensemble = _spec("market.ensemble", run_kind="cohort")
    run_dir = store.publish(
        ensemble,
        members=[MemberWeight(missing.run_id, 1.0)],
    )
    catalog = AlphaPoolCatalog(tmp_path / "alpha_pool.duckdb")

    with pytest.raises(ValueError, match="Unresolved or cyclic ensemble lineage"):
        catalog.register_manifest(run_dir / "manifest.json")
    assert catalog.runs().empty


def test_catalog_rebuilds_from_manifests_in_lineage_order(tmp_path: Path) -> None:
    store = ImmutableArtifactStore(tmp_path / "artifacts")
    member_a = _spec("market.member_a")
    member_b = _spec("market.member_b")
    for spec in (member_a, member_b):
        store.publish(
            spec,
            metrics=[MetricValue("validation", "gross_return", 0.01)],
            frames={"target_weights": _frame()},
        )
    ensemble = _spec("market.family", run_kind="family")
    store.publish(
        ensemble,
        members=[
            MemberWeight(member_a.run_id, 0.5),
            MemberWeight(member_b.run_id, 0.5),
        ],
        frames={"target_weights": _frame()},
    )

    catalog = rebuild_catalog(tmp_path / "alpha_pool.duckdb", tmp_path / "artifacts")

    assert set(catalog.runs()["run_id"]) == {
        member_a.run_id,
        member_b.run_id,
        ensemble.run_id,
    }
    assert len(catalog.members()) == 2
    rebuilt = rebuild_catalog(tmp_path / "alpha_pool.duckdb", tmp_path / "artifacts")
    assert len(rebuilt.runs()) == 3


def test_rebuild_rejects_corrupted_artifact(tmp_path: Path) -> None:
    store = ImmutableArtifactStore(tmp_path / "artifacts")
    spec = _spec("market.corrupt")
    run_dir = store.publish(spec, frames={"signal": _frame()})
    (run_dir / "signal.parquet").write_bytes(b"corrupted")

    with pytest.raises(ValueError, match="hash mismatch"):
        rebuild_catalog(tmp_path / "alpha_pool.duckdb", tmp_path / "artifacts")


def test_trusted_run_rejects_interval_over_63_days() -> None:
    with pytest.raises(ValueError, match="must not exceed 63"):
        _spec("market.too_slow", rebalance_days=64)


def test_manifest_contains_resolved_provenance_and_artifact_hash(tmp_path: Path) -> None:
    store = ImmutableArtifactStore(tmp_path / "artifacts")
    spec = _spec("consensus.hybrid", family="consensus")
    run_dir = store.publish(
        spec,
        frames={"daily_returns": _frame()},
        provenance={"logical_inputs": ["adjusted_return", "consensus_valuation"]},
    )

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run"]["run_id"] == spec.run_id
    assert manifest["provenance"]["logical_inputs"] == [
        "adjusted_return",
        "consensus_valuation",
    ]
    assert len(manifest["artifacts"]["daily_returns"]["sha256"]) == 64


def _spec(
    alpha_key: str,
    *,
    family: str = "market",
    run_kind: str = "atomic",
    status: str = "complete",
    rebalance_days: int = 21,
    attempt: int = 0,
) -> RunSpec:
    return RunSpec(
        alpha_key=alpha_key,
        family=family,
        run_kind=run_kind,
        research_track="trusted",
        order_calendar_key="common_21d_lag1",
        rebalance_days=rebalance_days,
        status=status,
        config_hash="a" * 64,
        data_fingerprint="b" * 64,
        attempt=attempt,
        created_at="2026-07-24T00:00:00Z",
    )


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"A": [0.1, 0.2], "B": [-0.1, -0.2]},
        index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="date"),
    )
