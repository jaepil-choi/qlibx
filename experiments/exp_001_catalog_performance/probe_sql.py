"""Micro-benchmark catalog recovery and event-order SQL alternatives."""

import json
import tempfile
import time
from pathlib import Path

import duckdb

with tempfile.TemporaryDirectory() as temporary:
    connection = duckdb.connect(str(Path(temporary) / "catalog.duckdb"))
    connection.execute("CREATE TABLE ev (event_order BIGINT, payload VARCHAR)")
    connection.execute("BEGIN TRANSACTION")
    connection.executemany(
        "INSERT INTO ev VALUES (?, ?)",
        [(index, "x" * 200) for index in range(20000)],
    )
    connection.execute("COMMIT")
    connection.execute("CREATE SEQUENCE ev_seq START 20001")
    for label, sql in {
        "max(event_order) over 20k rows": (
            "SELECT coalesce(max(event_order), 0) + 1 FROM ev"
        ),
        "nextval(sequence)": "SELECT nextval('ev_seq')",
    }.items():
        connection.execute(sql).fetchall()
        start = time.perf_counter()
        for _ in range(200):
            connection.execute(sql).fetchall()
        print(f"{label:38s} {(time.perf_counter() - start) / 200 * 1000:6.3f} ms")

    connection.execute(
        "CREATE TABLE pe ("
        "event_order BIGINT, attempt_id VARCHAR, phase VARCHAR, event_json VARCHAR)"
    )
    rows = []
    for index in range(20000):
        phase = "catalog_committed" if index % 4 == 3 else "staged"
        payload = json.dumps({"event_schema_version": 1, "padding": "x" * 100})
        rows.append((index, f"attempt-{index // 4}", phase, payload))
    connection.execute("BEGIN TRANSACTION")
    connection.executemany("INSERT INTO pe VALUES (?, ?, ?, ?)", rows)
    connection.execute("COMMIT")
    scenarios = {
        "full event log": "SELECT event_json FROM pe ORDER BY event_order",
        "unterminated attempts only": (
            "SELECT event_json FROM pe WHERE attempt_id NOT IN ("
            "SELECT attempt_id FROM pe WHERE phase IN "
            "('catalog_committed', 'recovered_abandoned')) ORDER BY event_order"
        ),
        "event schema-version guard": (
            "SELECT event_order FROM pe WHERE "
            "json_extract(event_json, '$.event_schema_version') <> CAST('1' AS JSON) LIMIT 1"
        ),
    }
    for label, sql in scenarios.items():
        selected = connection.execute(sql).fetchall()
        start = time.perf_counter()
        for _ in range(50):
            connection.execute(sql).fetchall()
        print(
            f"{label:38s} {(time.perf_counter() - start) / 50 * 1000:6.3f} ms "
            f"rows={len(selected)}"
        )