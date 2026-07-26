from __future__ import annotations

import json
from pathlib import Path

from qlib_extended.research import (
    AlphaPoolCatalog,
    DataCatalog,
    ImmutableArtifactStore,
    WalkForwardScheme,
    load_alpha_definitions,
    publish_financial_shadow_outputs,
)


ROOT = Path(__file__).resolve().parents[1]


def test_existing_quarterly_financial_research_is_shadow_only(tmp_path: Path) -> None:
    data_catalog = DataCatalog.from_directory(ROOT / "configs" / "data")
    definition = load_alpha_definitions(
        ROOT / "configs" / "alphas", data_catalog=data_catalog
    )["financial.statement_and_dividend.quarterly_shadow"]
    catalog = AlphaPoolCatalog(tmp_path / "alpha_pool.duckdb")

    summary = publish_financial_shadow_outputs(
        ROOT / "research" / "financial",
        definition=definition,
        scheme=WalkForwardScheme.from_yaml(ROOT / "configs" / "splits.yaml"),
        store=ImmutableArtifactStore(tmp_path / "artifacts"),
        catalog=catalog,
    )

    runs = catalog.runs()
    assert summary.atomic_runs == 4
    assert summary.family_runs == 1
    assert summary.deprecated_252d_candidates == 2
    assert set(runs["research_track"]) == {"financial_shadow"}
    assert runs["rebalance_days"].max() == 63
    assert set(runs["run_kind"]) == {"atomic", "family"}
    assert len(catalog.members()) == 4
    assert "historical_full" in set(catalog.metrics()["segment"])
    assert "walk_forward_2021" in set(catalog.metrics()["segment"])
    for artifact_dir in runs["artifact_dir"]:
        manifest = json.loads(
            (tmp_path / artifact_dir / "manifest.json").read_text(encoding="utf-8")
        )
        assert "shadow only" in manifest["provenance"]["classification"]
        assert "not a newly frozen" in manifest["provenance"]["selection_audit"]
