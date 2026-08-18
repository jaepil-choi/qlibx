"""Extract a de-minimis KOSPI 200 cross-section with industry codes.

This fixture exists for one thing the wide figure-3 panels cannot provide: a **structurally rank
deficient** exposure matrix built from real classifications. A market column alongside a complete
set of industry dummies is exactly dependent, because the dummies sum to the market column, and
that exact singularity is the case a regression must refuse by naming the column rather than
returning a number.

Uneven industry membership, including the single-name industries recorded below, is what makes this
a realistic classification rather than a contrived one. It is **not** what causes the singularity:
`neutralize` performs no within-group centring, so a one-member group is not special to it. The
test that consumes this asserts both directions rather than implying otherwise.

Scope is deliberately small. This is vendor-derived, so it is an excerpt rather than a
redistribution: a few month-end classification dates, the KOSPI 200 members on them, their industry
codes and index weights, and the daily returns for those names over the same span. Wide enough that
the thin-industry case is real, narrow enough that committing it is honest.

Classification is month-end only in the source, which is why the dates are month-ends rather than a
continuous window.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import duckdb

MEMBERS = Path("data/preprocessed/k200_members.parquet")
SECTORS = Path("data/preprocessed/sector_classification.parquet")
PRICES = Path("data/preprocessed/adjusted_prices.parquet")
FIXTURE = Path("tests/fixtures/real_k200")
CLASSIFICATION_DATES = 3


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _extract(connection: duckdb.DuckDBPyConnection) -> dict[str, object]:
    dates = [
        row[0]
        for row in connection.execute(
            f"SELECT DISTINCT date FROM read_parquet('{SECTORS.as_posix()}') "
            f"ORDER BY date DESC LIMIT {CLASSIFICATION_DATES}"
        ).fetchall()
    ]
    dates.sort()
    span = [str(value)[:10] for value in dates]
    quoted = ", ".join(f"DATE '{value}'" for value in span)

    connection.execute(
        f"""
        CREATE OR REPLACE TABLE cross_section AS
        SELECT
            s.date            AS date,
            k.ticker          AS ticker,
            s.industry_code   AS industry_code,
            k.index_weight    AS index_weight
        FROM read_parquet('{SECTORS.as_posix()}') s
        JOIN read_parquet('{MEMBERS.as_posix()}') k
          ON k.ticker = s.ticker
         AND k.date = (
                SELECT max(date) FROM read_parquet('{MEMBERS.as_posix()}')
                WHERE date <= s.date
            )
        WHERE s.date IN ({quoted}) AND k.is_k200_member
        ORDER BY date, ticker
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE returns AS
        SELECT p.date AS date, p.ticker AS ticker, p.return AS return
        FROM read_parquet('{PRICES.as_posix()}') p
        WHERE p.ticker IN (SELECT DISTINCT ticker FROM cross_section)
          AND p.date BETWEEN DATE '{span[0]}' AND DATE '{span[-1]}'
        ORDER BY date, ticker
        """
    )

    FIXTURE.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"COPY cross_section TO '{(FIXTURE / 'cross_section.parquet').as_posix()}' (FORMAT PARQUET)"
    )
    connection.execute(
        f"COPY returns TO '{(FIXTURE / 'returns.parquet').as_posix()}' (FORMAT PARQUET)"
    )

    thin = connection.execute(
        """
        SELECT date, industry_code, count(*) AS names
        FROM cross_section GROUP BY 1, 2 HAVING count(*) = 1
        ORDER BY date, industry_code
        """
    ).fetchall()
    shape = connection.execute(
        "SELECT count(*), count(DISTINCT ticker), count(DISTINCT industry_code) FROM cross_section"
    ).fetchone()
    return_rows = connection.execute("SELECT count(*) FROM returns").fetchone()[0]

    return {
        "purpose": (
            "A de-minimis KOSPI 200 cross-section with industry codes, so a structurally rank "
            "deficient exposure matrix can be built from real classifications rather than an "
            "invented one. The singularity comes from a complete dummy set summing to a market "
            "column, not from the single-name industries recorded here; those make the "
            "classification realistic and are asserted to be accepted rather than refused."
        ),
        "provenance": (
            "Vendor-derived excerpt from the local warehouse, not a redistribution of the source. "
            "Classification is month-end only in the vendor data, which is why the dates are "
            "month-ends rather than a continuous window."
        ),
        "classification_dates": span,
        "rows": shape[0],
        "instruments": shape[1],
        "industries": shape[2],
        "return_rows": return_rows,
        "single_name_industries": [
            {"date": str(row[0])[:10], "industry_code": int(row[1])} for row in thin
        ],
        "sources_sha256": {
            "k200_members": _digest(MEMBERS),
            "sector_classification": _digest(SECTORS),
            "adjusted_prices": _digest(PRICES),
        },
        "committed_sha256": {
            name: _digest(FIXTURE / name) for name in ("cross_section.parquet", "returns.parquet")
        },
        "committed_bytes": {
            name: (FIXTURE / name).stat().st_size
            for name in ("cross_section.parquet", "returns.parquet")
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed fixture against its recorded hashes without rewriting",
    )
    arguments = parser.parse_args()

    if arguments.check:
        manifest = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))
        drift = [
            name
            for name, digest in manifest["committed_sha256"].items()
            if _digest(FIXTURE / name) != digest
        ]
        if drift:
            print(f"committed panels drifted: {drift}", file=sys.stderr)
            return 1
        print("committed panels match their recorded hashes")
        return 0

    for path in (MEMBERS, SECTORS, PRICES):
        if not path.is_file():
            raise SystemExit(f"warehouse input is missing: {path}")

    connection = duckdb.connect()
    try:
        manifest = _extract(connection)
    finally:
        connection.close()

    (FIXTURE / "fixture.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    total = sum(manifest["committed_bytes"].values())
    print(f"wrote {FIXTURE} ({total / 1e3:.1f} KB)")
    print(
        f"  {manifest['rows']} rows, {manifest['instruments']} instruments, "
        f"{manifest['industries']} industries over {manifest['classification_dates']}"
    )
    print(f"  single-name industries: {len(manifest['single_name_industries'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
