"""What the workspace writes, it reads back and writes again byte-for-byte.

Deletion campaign Step 4 (record `145`) moves the workspace document onto pydantic models one
section at a time. The property that must hold at every step is the round trip: a document the
current tree wrote opens, and writing the same state again produces the same bytes. A model that
reordered keys, dropped a default or re-spelled a value would show up here as a diff, printed in
full so the reader sees exactly which section moved.

The fixture is built through the public API rather than pasted, so it is always the shape the
tree writes today; the on-disk shape is pinned separately by `tests/test_workspace.py`.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import duckdb

from vqapr.public import DatasetRegistration, SourceSpec, register_dataset
from vqapr.workspace import Workspace


def _parquet(path: Path) -> Path:
    duckdb.connect().execute(
        "COPY (SELECT TIMESTAMPTZ '2024-03-04 15:30:00+09' AS available_at, 'A' AS instrument, "
        f"1.0 AS close) TO '{path.as_posix()}' (FORMAT PARQUET)"
    )
    return path


def _populate(root: Path) -> Workspace:
    prices = _parquet(root / "prices.parquet")
    register_dataset(
        root,
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
            grain="instrument_instant",
        ),
        SourceSpec.of("prices-source", prices),
    )
    register_dataset(
        root,
        DatasetRegistration.of(
            "hive-prices",
            "hive-source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
            grain="instrument_instant",
        ),
        SourceSpec.of("hive-source", prices, hive_partitioned=True),
    )
    return Workspace.open(root)


def test_the_document_the_tree_writes_reads_back_and_writes_again_identically(
    tmp_path: Path,
) -> None:
    workspace = _populate(tmp_path)
    written = workspace.path.read_text(encoding="utf-8")

    reopened = Workspace.open(tmp_path)
    reopened._write(*reopened._state())
    rewritten = reopened.path.read_text(encoding="utf-8")

    diff = "".join(
        difflib.unified_diff(
            written.splitlines(keepends=True),
            rewritten.splitlines(keepends=True),
            "written",
            "rewritten",
        )
    )
    assert written == rewritten, f"the round trip changed the document:\n{diff}"


def test_what_was_read_is_what_was_registered(tmp_path: Path) -> None:
    workspace = _populate(tmp_path)
    sources = {str(source.source_id): source for source in workspace.sources}
    assert sources["hive-source"].hive_partitioned is True
    assert sources["prices-source"].hive_partitioned is False
    assert sources["prices-source"].path == tmp_path / "prices.parquet"
