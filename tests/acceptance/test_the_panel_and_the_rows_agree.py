"""The same arithmetic on a panel registration and on a rows registration is byte-identical.

Campaign Step 5's regression, in the read-path campaign's own shape (lane C): one table registered
twice -- `instrument_instant`, read with `read(alias, field)` as a panel window, and `rows`, read
with `rows(alias)` as observations -- two models with the same arithmetic, one datamodel run
computing both (record `148`), and a bidirectional anti-join of **zero rows**. Checked before any
timing is read: a panel that was faster and different would be a different dataset, not a faster
one.

The table is balanced (every name publishes at every instant), because on a balanced table the
two lookback meanings coincide -- the last N table rows and each name's own last N instants are the
same rows. That coincidence is exactly what made the meaning change silent (design §2.4), and it
is what makes the two registrations comparable here.
"""

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from vqapr.data.dataset import DatasetRegistration
from vqapr.data.source import SourceSpec
from vqapr.public import freeze, register_data_model, register_dataset, run
from vqapr.run.engine.loop import DataModelResult
from vqapr.workspace.registry import WORKSPACE_DIRECTORY
from vqapr.workspace.run_definition import DataModelEntry, RunDefinition, RunSchedule

KST = ZoneInfo("Asia/Seoul")

_MODELS = """
from vqapr import public as vq


def _score(values):
    return -(values[-1] / values[0] - 1.0)


class ReversalOnPanel(vq.DataModel):
    def inputs(self):
        return {"prices": vq.DatasetInput(
            dataset_id="px_panel", fields=("close",), lookback=vq.RowsLookback(rows=3)
        )}

    def compute(self, context):
        window = context.read("prices", "close")
        closes = {
            name: [float(v) for v in window.values[name] if v is not None]
            for name in window.instruments
        }
        return tuple(
            {"instrument": name, "score": _score(values)}
            for name, values in sorted(closes.items())
            if len(values) == 3
        )


class ReversalOnRows(vq.DataModel):
    def inputs(self):
        return {"prices": vq.DatasetInput(
            dataset_id="px_rows", fields=("close",), lookback=vq.InstantsLookback(instants=3)
        )}

    def compute(self, context):
        closes = {}
        for row in context.rows("prices"):
            if row.values["close"] is not None:
                closes.setdefault(row.instrument_id, []).append(float(row.values["close"]))
        return tuple(
            {"instrument": name, "score": _score(values)}
            for name, values in sorted(closes.items())
            if len(values) == 3
        )
"""


def _balanced_parquet(root: Path) -> Path:
    out = root / "prices.parquet"
    rows = ", ".join(
        f"(TIMESTAMPTZ '2024-03-{day:02d} 15:30:00+09', '{name}', {base + day * step}.0::DOUBLE)"
        for day in range(1, 9)
        for name, base, step in (("A", 100, 1), ("B", 50, 2), ("C", 80, 3))
    )
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES {rows}) AS t(available_at, instrument, close)) "
        f"TO '{out.as_posix()}' (FORMAT PARQUET)"
    )
    return out


def _register(root: Path, parquet: Path, dataset_id: str, grain: str) -> None:
    register_dataset(
        root,
        DatasetRegistration.of(
            dataset_id,
            f"{dataset_id}-source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
            field_types={"close": "DOUBLE"},
            grain=grain,
        ),
        SourceSpec.of(f"{dataset_id}-source", parquet),
    )


def _chunks(result: DataModelResult) -> str:
    """The duckdb expression over every chunk a datamodel run wrote: its output is a directory."""
    return (
        "SELECT available_at, instrument, score "
        f"FROM read_parquet('{result.output_path.as_posix()}/*.parquet')"
    )


def test_a_panel_read_and_a_rows_read_of_one_table_publish_byte_identical_datasets(
    tmp_path: Path,
) -> None:
    parquet = _balanced_parquet(tmp_path)
    _register(tmp_path, parquet, "px_panel", "instrument_instant")
    _register(tmp_path, parquet, "px_rows", "rows")
    models = tmp_path / "models.py"
    models.write_text(_MODELS, encoding="utf-8")
    register_data_model(tmp_path, "on-panel", models, "ReversalOnPanel")
    register_data_model(tmp_path, "on-rows", models, "ReversalOnRows")
    # Every second trading day at 16:00 from 3/4 -- the 4th, 6th and 8th -- so each model sees
    # a full 3-row window on every day it is called (design §3.4: the day filter is the rule's).
    # One model per run (design §2.3), so the two readings are two runs. Comparing them is
    # the point of this test and is exactly what the dataset graph makes possible: what a run
    # writes is named, and a later reader compares the named things rather than two members of
    # one execution.
    def _definition(run_id: str, component: str, dataset: str, reads: str) -> RunDefinition:
        return RunDefinition(
            run_id=run_id,
            datamodel=DataModelEntry(component, ("score",)),
            instruments=("A", "B", "C"),
            timezone="Asia/Seoul",
            # A datamodel run names the dataset whose days are its trading days (design §3.3).
            schedule=RunSchedule(every="2d", at=(time(16, 0),), days_from=reads),
            start=datetime(2024, 3, 4, tzinfo=KST),
            end=datetime(2024, 3, 9, tzinfo=KST),
            writes=dataset,
        )

    definitions = (
        _definition("agree-panel", "on-panel", "reversal_panel", "px_panel"),
        _definition("agree-rows", "on-rows", "reversal_rows", "px_rows"),
    )

    outcomes = [
        run(
            tmp_path,
            freeze(tmp_path, definition),
            store_root=tmp_path / WORKSPACE_DIRECTORY,
        )
        for definition in definitions
    ]

    panel, rows = outcomes[0].result("on-panel"), outcomes[1].result("on-rows")
    assert isinstance(panel, DataModelResult) and isinstance(rows, DataModelResult)
    con = duckdb.connect()
    try:
        left, right = _chunks(panel), _chunks(rows)
        assert con.execute(f"SELECT count(*) FROM (({left}) EXCEPT ({right}))").fetchone()[0] == 0
        assert con.execute(f"SELECT count(*) FROM (({right}) EXCEPT ({left}))").fetchone()[0] == 0
        assert con.execute(f"SELECT count(*) FROM ({left})").fetchone()[0] == 9, (
            "three names, three instants"
        )
    finally:
        con.close()
