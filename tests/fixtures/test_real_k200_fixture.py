"""The vendor cross-section, and the thin industry it exists to carry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pytest

FIXTURE = Path(__file__).resolve().parent / "real_k200"
PANELS = ("cross_section.parquet", "returns.parquet")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))


def test_every_committed_panel_matches_its_recorded_hash(manifest: dict) -> None:
    for name in PANELS:
        assert (FIXTURE / name).is_file(), f"{name} is missing"
        digest = hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest()
        assert digest == manifest["committed_sha256"][name]


def test_the_slice_is_small_enough_to_be_an_excerpt(manifest: dict) -> None:
    """Vendor-derived, so the size is part of the honesty, not an implementation detail."""
    total = sum(manifest["committed_bytes"].values())

    assert total < 500_000, f"{total} bytes is no longer an excerpt"
    assert "not a redistribution" in manifest["provenance"]


def test_a_single_name_industry_is_present(manifest: dict) -> None:
    """The whole reason this fixture exists.

    A single-name industry gives a dummy column that vanishes under within-group centring, which is
    an exact singularity rather than an ill-conditioned matrix. A regression must refuse it by
    naming the column, and it can only be shown to do that against a real one.
    """
    thin = manifest["single_name_industries"]

    assert thin, "no single-name industry, so the rank-deficiency case cannot be exercised"
    assert all({"date", "industry_code"} == set(entry) for entry in thin)


def test_the_thin_industry_claim_holds_in_the_committed_data(manifest: dict) -> None:
    """Verified against the parquet, not against the manifest that describes it."""
    connection = duckdb.connect()
    try:
        counted = connection.execute(
            f"""
            SELECT date, industry_code, count(*) AS names
            FROM read_parquet('{(FIXTURE / "cross_section.parquet").as_posix()}')
            GROUP BY 1, 2 HAVING count(*) = 1
            """
        ).fetchall()
    finally:
        connection.close()

    observed = {(str(row[0])[:10], int(row[1])) for row in counted}
    recorded = {
        (entry["date"], entry["industry_code"]) for entry in manifest["single_name_industries"]
    }
    assert observed == recorded


def test_the_cross_section_is_a_real_index_membership(manifest: dict) -> None:
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            f"""
            SELECT date, count(*) AS names, count(DISTINCT industry_code) AS industries,
                   round(sum(index_weight), 6) AS weight_sum
            FROM read_parquet('{(FIXTURE / "cross_section.parquet").as_posix()}')
            GROUP BY 1 ORDER BY 1
            """
        ).fetchall()
    finally:
        connection.close()

    assert len(rows) == len(manifest["classification_dates"])
    for _, names, industries, weight_sum in rows:
        assert names == 200, "a KOSPI 200 cross-section has two hundred names"
        assert 1 < industries < names, "industries must partition the names non-trivially"
        # The vendor publishes weights rounded to four decimals, so a two-hundred-name sum
        # lands within a rounding step of one rather than on it: the committed dates measure
        # 0.9996, 0.9999 and 1.0000007. Asserting exact equality would only be satisfiable by
        # renormalising, which would store a number the vendor never published.
        assert abs(float(weight_sum) - 1.0) < 1e-3, "index weights must sum to one within rounding"


def test_returns_cover_the_instruments_in_the_cross_section() -> None:
    connection = duckdb.connect()
    try:
        uncovered = connection.execute(
            f"""
            SELECT count(DISTINCT c.ticker)
            FROM read_parquet('{(FIXTURE / "cross_section.parquet").as_posix()}') c
            LEFT JOIN read_parquet('{(FIXTURE / "returns.parquet").as_posix()}') r
              ON r.ticker = c.ticker
            WHERE r.ticker IS NULL
            """
        ).fetchone()[0]
    finally:
        connection.close()

    assert uncovered == 0, f"{uncovered} instruments have no return in the committed slice"


def test_classification_dates_are_month_ends_as_the_source_provides_them(manifest: dict) -> None:
    """Stated so a reader does not mistake the gaps for missing data."""
    assert "month-end only" in manifest["provenance"]
    assert len(manifest["classification_dates"]) >= 2
