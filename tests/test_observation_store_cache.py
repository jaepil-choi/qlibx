import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from qlibx import OutcomeStatus, QlibxProject
from qlibx.data import AvailableAtField, DatasetRegistration, ObservationStore, SourceFormat
from qlibx.data import store as store_module
from qlibx.data.store import DataSnapshotError


def register_source(
    tmp_path: Path,
    *,
    dataset_id: str = "market",
    source_timezone: str = "UTC",
):
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
            source_timezone=source_timezone,
            available_at=AvailableAtField(field="available_at"),
            logical_key=("observed_at", "available_at", "instrument"),
            semantic_bindings={"value": "value", "alternate": "alternate"},
            source_provenance="observation cache fixture",
        )
    )
    assert outcome.status is OutcomeStatus.COMPLETE
    return outcome.result


def write_source(path: Path, *, first_value: str = "1.0") -> None:
    path.write_text(
        "observed_at,available_at,instrument,value,alternate\n"
        f"2025-01-01T00:00:00,2025-01-01T01:00:00,A,{first_value},10.0\n"
        "2025-01-02T00:00:00,2025-01-02T01:00:00,B,2.0,20.0\n",
        encoding="utf-8",
    )


def test_warm_cache_hashes_every_query_but_reads_and_normalizes_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "market.csv"
    write_source(source)
    registered = register_source(tmp_path)
    store = ObservationStore()
    counts = {"hash": 0, "read": 0, "normalize": 0}
    real_hash = store_module.file_hash
    real_read = pd.read_csv
    real_normalize = store_module.normalize_timestamps

    def counted_hash(path: Path) -> str:
        counts["hash"] += 1
        return real_hash(path)

    def counted_read(*args, **kwargs):
        counts["read"] += 1
        return real_read(*args, **kwargs)

    def counted_normalize(*args, **kwargs):
        counts["normalize"] += 1
        return real_normalize(*args, **kwargs)

    monkeypatch.setattr(store_module, "file_hash", counted_hash)
    monkeypatch.setattr(pd, "read_csv", counted_read)
    monkeypatch.setattr(store_module, "normalize_timestamps", counted_normalize)

    first = store.query(
        registered,
        field="value",
        as_of=datetime(2025, 1, 1, 2, tzinfo=UTC),
    )
    first.loc[:, "value"] = 999.0
    second = store.query(
        registered,
        field="value",
        as_of=datetime(2025, 1, 3, tzinfo=UTC),
    )

    assert second["value"].tolist() == [1.0, 2.0]
    assert counts == {"hash": 2, "read": 1, "normalize": 2}


def test_warm_cache_rejects_deleted_source(tmp_path: Path) -> None:
    source = tmp_path / "market.csv"
    write_source(source)
    registered = register_source(tmp_path)
    store = ObservationStore()
    store.query(registered, field="value", as_of=datetime(2025, 1, 3, tzinfo=UTC))

    source.unlink()

    with pytest.raises(DataSnapshotError, match="no longer matches registration"):
        store.query(registered, field="value", as_of=datetime(2025, 1, 3, tzinfo=UTC))


def test_warm_cache_rejects_same_size_same_mtime_source_drift(tmp_path: Path) -> None:
    source = tmp_path / "market.csv"
    write_source(source)
    registered = register_source(tmp_path)
    store = ObservationStore()
    store.query(registered, field="value", as_of=datetime(2025, 1, 3, tzinfo=UTC))
    original_stat = source.stat()

    write_source(source, first_value="9.0")
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    with pytest.raises(DataSnapshotError, match="no longer matches registration"):
        store.query(registered, field="value", as_of=datetime(2025, 1, 3, tzinfo=UTC))


def test_cache_isolated_by_registration_contract_and_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "market.csv"
    write_source(source)
    utc_registration = register_source(tmp_path, dataset_id="market-utc")
    seoul_registration = register_source(
        tmp_path,
        dataset_id="market-seoul",
        source_timezone="Asia/Seoul",
    )
    store = ObservationStore()
    real_read = pd.read_csv
    read_count = 0

    def counted_read(*args, **kwargs):
        nonlocal read_count
        read_count += 1
        return real_read(*args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", counted_read)
    cutoff = datetime(2024, 12, 31, 18, tzinfo=UTC)

    utc_frame = store.query(utc_registration, field="value", as_of=cutoff)
    seoul_frame = store.query(seoul_registration, field="value", as_of=cutoff)
    alternate = store.query(
        seoul_registration,
        field="alternate",
        as_of=datetime(2025, 1, 3, tzinfo=UTC),
    )

    assert utc_frame.empty
    assert seoul_frame["value"].tolist() == [1.0]
    assert alternate["value"].tolist() == [10.0, 20.0]
    assert read_count == 3