from __future__ import annotations

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from qlibx import Project
from qlibx.data import discover_data, inspect_data
from qlibx.errors import QlibxError


def test_parquet_discovery_is_read_only_and_does_not_guess_semantics(tmp_path: Path) -> None:
    project = Project.initialize(tmp_path)
    source = project.paths.source_data / "incoming" / "mystery.parquet"
    source.parent.mkdir(parents=True)
    pq.write_table(pa.table({"when": ["2025-01-01"], "code": ["A"], "value": [1.0]}), source)
    before = source.read_bytes()
    candidates = discover_data(project)
    assert [candidate.path for candidate in candidates] == ["data/incoming/mystery.parquet"]
    inspection = inspect_data(project, "data/incoming/mystery.parquet", sample_rows=1)
    assert inspection.read_only is True
    assert inspection.mutates == ()
    assert [column.name for column in inspection.tables[0].columns] == ["when", "code", "value"]
    assert "available_at source and rule" in inspection.unresolved_requirements
    assert source.read_bytes() == before


def test_discovery_excludes_generated_data_and_rejects_paths_outside_source_root(
    tmp_path: Path,
) -> None:
    project = Project.initialize(tmp_path)
    generated = project.paths.generated_data / "derived.parquet"
    pq.write_table(pa.table({"x": [1]}), generated)
    assert discover_data(project) == ()
    outside = tmp_path / "outside.parquet"
    pq.write_table(pa.table({"x": [1]}), outside)
    with pytest.raises(QlibxError, match="outside configured source_data"):
        inspect_data(project, outside)


def test_duckdb_inspection_requires_explicit_known_table_and_is_bounded(tmp_path: Path) -> None:
    project = Project.initialize(tmp_path)
    source = project.paths.source_data / "incoming.duckdb"
    with duckdb.connect(str(source)) as connection:
        connection.execute("create table observations as select 1 as item union all select 2")
    inspection = inspect_data(project, source, table="observations", sample_rows=1)
    assert inspection.tables[0].name == "observations"
    assert len(inspection.tables[0].sample) == 1
    with pytest.raises(QlibxError, match="table not found"):
        inspect_data(project, source, table="guessed")
