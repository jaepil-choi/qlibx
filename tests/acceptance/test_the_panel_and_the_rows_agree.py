"""The same arithmetic on a panel registration and on a rows registration is byte-identical.

Campaign Step 5's regression, in the read-path campaign's own shape (lane C): one table registered
twice -- `instrument_instant`, read with `read(alias, field)` as a panel window, and `rows`, read
with `rows(alias)` as observations -- two models with the same arithmetic, two materializations,
and a bidirectional anti-join of **zero rows**. Checked before any timing is read: a panel that
was faster and different would be a different dataset, not a faster one.

The table is balanced (every name publishes at every instant), because on a balanced table the
two lookback meanings coincide -- the last N table rows and each name's own last N instants are the
same rows. That coincidence is exactly what made the meaning change silent (design §2.4), and it
is what makes the two registrations comparable here.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.flow.materialize import MaterializationSpec, materialize
from vqapr.public import register_data_model, register_dataset

KST = ZoneInfo("Asia/Seoul")

_MODELS = '''
from vqapr import authoring as va


def _score(values):
    return -(values[-1] / values[0] - 1.0)


class ReversalOnPanel(va.DataModel):
    def inputs(self):
        return {"prices": va.DatasetInput(dataset_id="px_panel", fields=("close",), lookback=va.RowsLookback(rows=3))}

    def compute(self, context):
        window = context.read("prices", "close")
        closes = {name: [float(v) for v in window.values[name] if v is not None] for name in window.instruments}
        return tuple(
            {"instrument": name, "score": _score(values)}
            for name, values in sorted(closes.items())
            if len(values) == 3
        )


class ReversalOnRows(va.DataModel):
    def inputs(self):
        return {"prices": va.DatasetInput(dataset_id="px_rows", fields=("close",), lookback=va.InstantsLookback(instants=3))}

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
'''


def _balanced_parquet(root: Path) -> Path:
    out = root / "prices.parquet"
    rows = ", ".join(
        f"(TIMESTAMPTZ '2024-03-{day:02d} 15:30:00+09', '{name}', {base + day * step}.0)"
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
            grain=grain,
        ),
        SourceSpec.of(f"{dataset_id}-source", parquet),
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
    times = tuple(datetime(2024, 3, day, 16, tzinfo=KST) for day in (4, 6, 8))

    panel = materialize(
        tmp_path,
        "on-panel",
        MaterializationSpec.of("reversal_panel", value_fields=("score",)),
        evaluation_times=times,
        instruments=("A", "B", "C"),
    )
    rows = materialize(
        tmp_path,
        "on-rows",
        MaterializationSpec.of("reversal_rows", value_fields=("score",)),
        evaluation_times=times,
        instruments=("A", "B", "C"),
    )

    con = duckdb.connect()
    try:
        left = f"SELECT available_at, instrument, score FROM '{panel.output_path.as_posix()}'"
        right = f"SELECT available_at, instrument, score FROM '{rows.output_path.as_posix()}'"
        assert con.execute(f"SELECT count(*) FROM (({left}) EXCEPT ({right}))").fetchone()[0] == 0
        assert con.execute(f"SELECT count(*) FROM (({right}) EXCEPT ({left}))").fetchone()[0] == 0
        assert con.execute(f"SELECT count(*) FROM ({left})").fetchone()[0] == 9, "three names, three instants"
    finally:
        con.close()
