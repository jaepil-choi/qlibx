"""`register-dataset`'s profiler answers the falsifiable half and refuses the other half.

PRD §11.1 splits a registration proposal into what the data proves and what only a name suggests.
The script ships inside the skill, so it is executable product surface: a wrong finding here is
read as evidence by whoever runs it, which is worse than no script.

The finding this file mostly exists for is the float key. On the shipped sample panel `open`,
`high` and `low` were each unique across 6,900 rows -- true, and an accident of continuous values.
Reported as a key candidate it invites `key_fields: [open]`, which registers and then loses a row
the day two names open at the same price.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import duckdb
import pytest

import vqapr

SCRIPT = (
    Path(vqapr.__file__).parent
    / "agent"
    / "skills"
    / "register-dataset"
    / "scripts"
    / "profile_source.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("profile_source", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


profiler = _load()


@pytest.fixture(scope="module")
def bars(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A price bar table: two names, three sessions, an aware stamp, one late lister."""
    path = tmp_path_factory.mktemp("source") / "bars.parquet"
    duckdb.connect().execute(
        f"""
        COPY (
          SELECT * FROM (VALUES
            ('A', TIMESTAMPTZ '2024-01-02 15:30:00+09', 100.0, 105.0, 99.0, 104.0, 10),
            ('A', TIMESTAMPTZ '2024-01-03 15:30:00+09', 104.0, 108.0, 103.0, 107.0, 11),
            ('A', TIMESTAMPTZ '2024-01-04 15:30:00+09', 107.0, 110.0, 106.0, 109.0, 12),
            ('B', TIMESTAMPTZ '2024-01-03 15:30:00+09', 200.0, 206.0, 199.0, 205.0, 20),
            ('B', TIMESTAMPTZ '2024-01-04 15:30:00+09', 205.0, 209.0, 204.0, 208.0, 21)
          ) AS t(instrument, available_at, open, high, low, close, volume)
        ) TO '{path.as_posix()}' (FORMAT PARQUET)
        """
    )
    return path


def test_a_float_column_is_never_offered_as_a_key(bars: Path) -> None:
    """Uniqueness on a measurement is a coincidence, not a property of the table."""
    report = profiler.profile(bars)
    for candidate in report["unique_keys"]:
        assert not {"open", "high", "low", "close"} & set(candidate["fields"]), candidate


def test_the_logical_key_is_found(bars: Path) -> None:
    keys = [set(candidate["fields"]) for candidate in profiler.profile(bars)["unique_keys"]]
    assert {"available_at", "instrument"} in keys


def test_the_bar_ordering_is_reported_and_the_roles_are_not(bars: Path) -> None:
    """The relation is proven; which inner column is the open is not, and must be asked."""
    report = profiler.profile(bars)
    held = set(report["orderings_that_always_hold"])
    assert {"low <= open", "open <= high", "low <= close", "close <= high"} <= held

    rendered = profiler._render(report)
    assert "which of the ordered numbers is the OPEN" in rendered
    # No claim about which column that is, anywhere in the output.
    assert "is the open" not in rendered.lower().replace(
        "which of the ordered numbers is the open", ""
    )


def test_a_naive_timestamp_is_called_out(tmp_path: Path) -> None:
    """Registration refuses it, so the profiler must say so before the user prepares the file."""
    path = tmp_path / "naive.parquet"
    duckdb.connect().execute(
        f"""
        COPY (SELECT 'A' AS instrument, TIMESTAMP '2024-01-02 15:30:00' AS ts, 1.0 AS v)
        TO '{path.as_posix()}' (FORMAT PARQUET)
        """
    )
    report = profiler.profile(path)
    assert report["timestamps"]["ts"]["timezone_aware"] is False
    assert "NAIVE" in profiler._render(report)


def test_an_unbalanced_panel_shows_who_starts_late(bars: Path) -> None:
    coverage = profiler.profile(bars)["coverage_if"]
    assert coverage["balanced"] is False
    assert [span["value"] for span in coverage["late_starters"]] == ["B"]


def test_the_questions_are_the_ones_this_file_raises(tmp_path: Path) -> None:
    """A fixed list would ask about an opening price in a table that holds no prices.

    A section that reads the same every time is the one a reader learns to skip, and this is the
    section that must not be skipped.
    """
    path = tmp_path / "plain.csv"
    path.write_text("instrument,name\nA,first\nB,second\n", encoding="utf-8")
    rendered = profiler._render(profiler.profile(path))
    assert "which of the ordered numbers" not in rendered
    assert "observation, the publication, or a revision" not in rendered


def test_a_spreadsheet_is_refused_with_the_reason(tmp_path: Path) -> None:
    """Half-reading one would hide a conversion that changes what a column means."""
    path = tmp_path / "book.xlsx"
    path.write_bytes(b"not really a workbook")
    with pytest.raises(SystemExit) as refused:
        profiler.profile(path)
    assert "convert it deliberately" in str(refused.value)
