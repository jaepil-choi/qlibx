"""Measure validation cost on a cold DuckDB connection."""

import shutil
import tempfile
import time
from pathlib import Path

import duckdb

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    seed = root / "seed.duckdb"
    connection = duckdb.connect(str(seed))
    connection.execute("CREATE TABLE artifacts (a INTEGER, b VARCHAR)")
    connection.execute("CREATE TABLE artifact_edges (a INTEGER)")
    connection.execute("CREATE TABLE publication_events (a INTEGER)")
    connection.execute("CREATE TABLE catalog_metadata (schema_version INTEGER)")
    connection.execute("INSERT INTO catalog_metadata VALUES (1)")
    connection.close()

    information_schema = (
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    )
    duckdb_tables = "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main'"
    pragmas = [
        f"PRAGMA table_info('{table}')"
        for table in ("artifacts", "artifact_edges", "publication_events")
    ]
    version = "SELECT schema_version FROM catalog_metadata"
    scenarios = {
        "connect + close only": [],
        "current: information_schema + 3 PRAGMA + version": [
            information_schema,
            *pragmas,
            version,
        ],
        "duckdb_tables() + 3 PRAGMA + version": [duckdb_tables, *pragmas, version],
        "duckdb_tables() only": [duckdb_tables],
    }

    iterations = 60
    for label, statements in scenarios.items():
        work = root / "work.duckdb"
        total = 0.0
        for _ in range(iterations):
            shutil.copyfile(seed, work)
            start = time.perf_counter()
            current = duckdb.connect(str(work))
            for sql in statements:
                current.execute(sql).fetchall()
            current.close()
            total += time.perf_counter() - start
            work.unlink()
        print(f"{label:52s} {total / iterations * 1000:7.2f} ms")