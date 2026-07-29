from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from qlibx import Project, QlibxError
from qlibx.research import ResearchCatalog


def _publish(catalog: ResearchCatalog, session: str, value: int):
    attempt = catalog.begin(
        session_id=session,
        invocation={"strategy": session, "value": value},
        kind="alpha",
    )
    catalog.stage_frame(attempt, "alpha", pd.DataFrame({"value": [value]}))
    return catalog.publish(attempt, status="successful", metadata={"value": value})


def test_three_sessions_publish_and_projection_is_rebuildable(tmp_path: Path) -> None:
    catalog = ResearchCatalog.from_project(Project.initialize(tmp_path))
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = tuple(
            executor.map(lambda pair: _publish(catalog, *pair), [("a", 1), ("b", 2), ("c", 3)])
        )
    assert len({result.record_id for result in results}) == 3
    projection = catalog.rebuild_projection()
    with duckdb.connect(str(projection), read_only=True) as connection:
        assert connection.execute("select count(*) from records").fetchone()[0] == 3


def test_same_identity_different_content_conflicts(tmp_path: Path) -> None:
    catalog = ResearchCatalog.from_project(Project.initialize(tmp_path))
    first = catalog.begin(session_id="a", invocation={"x": 1}, kind="alpha", result_key="same")
    catalog.stage_json(first, "result", {"value": 1})
    catalog.publish(first, status="successful", metadata={})
    second = catalog.begin(session_id="b", invocation={"x": 2}, kind="alpha", result_key="same")
    catalog.stage_json(second, "result", {"value": 2})
    with pytest.raises(QlibxError) as conflict:
        catalog.publish(second, status="successful", metadata={})
    assert conflict.value.code == "QLIBX_RESEARCH_RESULT_IDENTITY_CONFLICT"
    assert conflict.value.context["result_key"] == "same"


def test_idempotent_result_returns_cache_hit(tmp_path: Path) -> None:
    catalog = ResearchCatalog.from_project(Project.initialize(tmp_path))
    first = catalog.begin(session_id="a", invocation={"x": 1}, kind="alpha")
    catalog.stage_json(first, "result", {"value": 1})
    published = catalog.publish(first, status="successful", metadata={"m": 1})
    second = catalog.begin(session_id="b", invocation={"x": 1}, kind="alpha")
    catalog.stage_json(second, "result", {"value": 1})
    cached = catalog.publish(second, status="successful", metadata={"m": 1})
    assert cached.cached is True
    assert cached.record_id == published.record_id


def test_uncommitted_manifest_is_not_visible(tmp_path: Path) -> None:
    catalog = ResearchCatalog.from_project(Project.initialize(tmp_path))
    (catalog.records / "orphan.json").write_text(
        '{"record_id":"orphan","status":"successful"}', encoding="utf-8"
    )
    assert catalog.list_results() == ()
    projection = catalog.rebuild_projection()
    with duckdb.connect(str(projection), read_only=True) as connection:
        assert connection.execute("select count(*) from records").fetchone()[0] == 0
