import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from qlibx import OutcomeStatus, QlibxProject
from qlibx.data import (
    AvailableAtField,
    DatasetRegistration,
    ObservationStore,
    RowsLookback,
    SourceFormat,
)
from qlibx.data import store as store_module
from qlibx.data.store import DataSnapshotError


def write_source(path: Path, *, first_value: str = "1.0") -> None:
    path.write_text(
        "observed_at,available_at,instrument,sequence,value,alternate\n"
        f"2025-01-01T00:00:00,2025-01-01T01:00:00,A,1,{first_value},10.0\n"
        "2025-01-02T00:00:00,2025-01-02T01:00:00,B,1,2.0,20.0\n",
        encoding="utf-8",
    )


def register_source(tmp_path: Path, *, dataset_id: str = "market"):
    project_root = tmp_path / "project"
    if not project_root.exists():
        QlibxProject.init(project_root, apply=True)
    project = QlibxProject.open(project_root)
    outcome = project.register_dataset(
        DatasetRegistration(
            dataset_id=dataset_id,
            source=str(tmp_path / "market.csv"),
            source_format=SourceFormat.CSV,
            instrument_field="instrument",
            observation_time_field="observed_at",
            source_timezone="UTC",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("observed_at", "available_at", "instrument", "sequence"),
            semantic_bindings={"value": "value", "alternate": "alternate"},
            source_provenance="normalized query snapshot fixture",
        )
    )
    assert outcome.status is OutcomeStatus.COMPLETE
    return outcome.result


def query(store: ObservationStore, registered, *, field: str = "value"):
    return store.query(
        registered,
        field=field,
        as_of=datetime(2025, 1, 3, tzinfo=UTC),
        lookback=RowsLookback(rows=10),
    )


def test_query_uses_duckdb_snapshot_without_pandas_source_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "market.csv"
    write_source(source)
    registered = register_source(tmp_path)

    def unexpected_reader(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("query must not use a pandas source reader")

    monkeypatch.setattr(pd, "read_csv", unexpected_reader)
    monkeypatch.setattr(pd, "read_parquet", unexpected_reader)
    frame = query(ObservationStore(), registered)

    assert frame["value"].tolist() == [1.0, 2.0]


def test_frozen_scope_hashes_source_and_snapshot_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "market.csv"
    write_source(source)
    registered = register_source(tmp_path)
    store = ObservationStore()
    real_hash = store_module.file_hash
    hash_count = 0

    def counted_hash(path: Path) -> str:
        nonlocal hash_count
        hash_count += 1
        return real_hash(path)

    monkeypatch.setattr(store_module, "file_hash", counted_hash)
    with store.frozen():
        query(store, registered)
        with store.frozen():
            query(store, registered, field="alternate")
        query(store, registered)
    assert hash_count == 2

    query(store, registered)
    query(store, registered)
    assert hash_count == 6


def test_query_rejects_deleted_or_changed_source(tmp_path: Path) -> None:
    source = tmp_path / "market.csv"
    write_source(source)
    registered = register_source(tmp_path)
    store = ObservationStore()
    query(store, registered)
    original_stat = source.stat()

    write_source(source, first_value="9.0")
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    with pytest.raises(DataSnapshotError) as raised:
        query(store, registered)
    assert raised.value.code == "DATASET_SOURCE_DRIFT"


def test_query_rejects_snapshot_tamper(tmp_path: Path) -> None:
    source = tmp_path / "market.csv"
    write_source(source)
    registered = register_source(tmp_path)
    assert registered.query_snapshot is not None
    snapshot = Path(registered.query_snapshot.path)
    snapshot.write_bytes(snapshot.read_bytes() + b"tamper")

    with pytest.raises(DataSnapshotError) as raised:
        query(ObservationStore(), registered)
    assert raised.value.code == "DATASET_QUERY_SNAPSHOT_DRIFT"
