"""Probe DuckDB connection coexistence rules constraining scoped caching."""

import subprocess
import sys
import tempfile
from pathlib import Path

import duckdb

print("duckdb", duckdb.__version__)
with tempfile.TemporaryDirectory() as temporary:
    database = Path(temporary) / "catalog.duckdb"
    writer = duckdb.connect(str(database))
    writer.execute("CREATE TABLE t (a INTEGER)")
    writer.execute("INSERT INTO t VALUES (1)")

    try:
        second = duckdb.connect(str(database))
        print("1. same-process second read-write: OK")
        second.close()
    except Exception as exc:
        print("1. same-process second read-write: FAIL", type(exc).__name__)

    try:
        reader = duckdb.connect(str(database), read_only=True)
        print("2. same-process read-only: OK")
        reader.close()
    except Exception as exc:
        print("2. same-process read-only: FAIL", type(exc).__name__, str(exc)[:160])

    try:
        cursor = writer.cursor()
        print("3. writer.cursor(): OK", cursor.execute("SELECT count(*) FROM t").fetchone())
        cursor.close()
    except Exception as exc:
        print("3. writer.cursor(): FAIL", type(exc).__name__)

    read_probe = (
        "import duckdb,sys; "
        "duckdb.connect(sys.argv[1], read_only=True).execute('SELECT 1')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", read_probe, str(database)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    print("4. other-process read-only:", "OK" if completed.returncode == 0 else "FAIL")

    write_probe = "import duckdb,sys; duckdb.connect(sys.argv[1]).execute('SELECT 1')"
    completed = subprocess.run(
        [sys.executable, "-c", write_probe, str(database)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    print("5. other-process read-write:", "OK" if completed.returncode == 0 else "FAIL")

    writer.close()
    completed = subprocess.run(
        [sys.executable, "-c", write_probe, str(database)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    print("6. other-process read-write after close:", "OK" if completed.returncode == 0 else "FAIL")