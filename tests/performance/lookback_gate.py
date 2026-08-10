"""Fresh-process performance gate for the normalized-Parquet exact rows query."""

from __future__ import annotations

import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

from qlibx.data import (
    AvailableAtField,
    ObservationStore,
    RowsLookback,
    SourceFormat,
)
from qlibx.data.contracts import (
    DatasetQuerySnapshot,
    RegisteredDataset,
    RegistrationEvidence,
)
from qlibx.data.registry import file_hash

ROW_COUNT = 2_000_000
INSTRUMENT_COUNT = 50
ROWS_PER_INSTRUMENT = ROW_COUNT // INSTRUMENT_COUNT
REQUESTED_ROWS = 60


def paths(root: Path) -> tuple[Path, Path]:
    return root / "source.csv", root / "normalized.parquet"


def setup(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    source, snapshot = paths(root)
    if source.is_file() and snapshot.is_file():
        return
    relation = f"""
        SELECT
            'A' || lpad(CAST(instrument_number AS VARCHAR), 6, '0') AS instrument,
            TIMESTAMPTZ '2020-01-01 00:00:00+00'
                + row_number * INTERVAL 1 minute AS available_at,
            TIMESTAMPTZ '2020-01-01 00:00:00+00'
                + row_number * INTERVAL 1 minute AS observation_time,
            CAST(row_number AS DOUBLE) AS value,
            row_number AS __key_000
        FROM range({INSTRUMENT_COUNT}) instruments(instrument_number)
        CROSS JOIN range({ROWS_PER_INSTRUMENT}) rows(row_number)
    """
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            f"COPY ({relation}) TO ? (HEADER, DELIMITER ',')",
            [str(source)],
        )
        connection.execute(
            f"COPY ({relation}) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(snapshot)],
        )
    finally:
        connection.close()


def registered(root: Path) -> RegisteredDataset:
    source, snapshot = paths(root)
    columns = (
        "instrument",
        "available_at",
        "observation_time",
        "value",
        "__key_000",
    )
    return RegisteredDataset(
        registration_schema_version=2,
        dataset_id="lookback-performance-gate",
        registration_identity="lookback-performance-gate:v2",
        physical_fingerprint=file_hash(source),
        schema_fingerprint="0" * 64,
        source=str(source),
        source_format=SourceFormat.CSV,
        instrument_field="instrument",
        observation_time_field="observation_time",
        available_at=AvailableAtField(field="available_at"),
        logical_key=("instrument", "available_at", "observation_time"),
        bindings={"value": "value"},
        source_bindings={"value": "value"},
        source_provenance="generated two-million-row performance fixture",
        evidence=RegistrationEvidence(
            row_count=ROW_COUNT,
            columns=columns,
            logical_key_unique=True,
            logical_key_null_count=0,
        ),
        query_snapshot=DatasetQuerySnapshot(
            path=str(snapshot),
            fingerprint=file_hash(snapshot),
            row_count=ROW_COUNT,
            columns=columns,
            logical_order_columns=("__key_000",),
        ),
    )


def baseline(root: Path) -> float:
    source, _ = paths(root)
    expected = file_hash(source)
    started = time.perf_counter()
    assert file_hash(source) == expected
    frame = pd.read_csv(
        source,
        usecols=(
            "instrument",
            "available_at",
            "observation_time",
            "value",
            "__key_000",
        ),
        parse_dates=["available_at", "observation_time"],
    )
    cutoff = pd.Timestamp(datetime(2020, 1, 28, 18, 39, tzinfo=UTC))
    frame = frame.loc[frame["available_at"] <= cutoff]
    result = (
        frame.sort_values(
            ["instrument", "available_at", "observation_time", "__key_000"],
            kind="mergesort",
        )
        .groupby("instrument", sort=True, group_keys=False)
        .tail(REQUESTED_ROWS)
    )
    assert len(result) == INSTRUMENT_COUNT * REQUESTED_ROWS
    return time.perf_counter() - started


def bounded(root: Path) -> float:
    dataset = registered(root)
    instruments = tuple(f"A{number:06d}" for number in range(INSTRUMENT_COUNT))
    store = ObservationStore()
    started = time.perf_counter()
    with store.frozen():
        result = store.query(
            dataset,
            field="value",
            as_of=datetime(2020, 1, 28, 18, 39, tzinfo=UTC),
            lookback=RowsLookback(rows=REQUESTED_ROWS),
            instruments=instruments,
        )
    assert len(result) == INSTRUMENT_COUNT * REQUESTED_ROWS
    return time.perf_counter() - started


def compare(root: Path) -> None:
    baseline_times: list[float] = []
    bounded_times: list[float] = []
    for _ in range(7):
        for mode, target in (("baseline", baseline_times), ("bounded", bounded_times)):
            completed = subprocess.run(
                [sys.executable, __file__, mode, str(root)],
                check=True,
                capture_output=True,
                text=True,
            )
            target.append(float(completed.stdout.strip()))
    baseline_median = statistics.median(baseline_times)
    bounded_median = statistics.median(bounded_times)
    ratio = bounded_median / baseline_median
    print(f"baseline_times={baseline_times}")
    print(f"bounded_times={bounded_times}")
    print(f"baseline_median={baseline_median:.6f}")
    print(f"bounded_median={bounded_median:.6f}")
    print(f"ratio={ratio:.6f}")
    if ratio > 0.5:
        raise SystemExit("bounded DuckDB median exceeds 50% of pandas baseline")


def main() -> None:
    mode = sys.argv[1]
    root = Path(sys.argv[2]).resolve()
    if mode == "setup":
        setup(root)
    elif mode == "baseline":
        print(f"{baseline(root):.9f}")
    elif mode == "bounded":
        print(f"{bounded(root):.9f}")
    elif mode == "compare":
        compare(root)
    else:
        raise SystemExit(f"unknown mode: {mode}")


if __name__ == "__main__":
    main()
