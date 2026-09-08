"""`register` speaks the point-in-time convention (`027`); a dataset names the run that wrote
it and a component list can be asked who reads a dataset (`082`).

`027`, reopened by the owner: nothing made a convention be spoken aloud. `available_at`,
`trade_at`, `at`, `timezone`, `selector` and `trade_price` are the fields whose whole content is
their meaning, and an author who typed them had never been told what they commit to. The rule
settled there: **one sentence per PIT-bearing concept, or nothing** -- a restatement long enough
to scroll past is the paragraph it was meant to replace.

`082`: "who reads this dataset" took 41 processes and 36 seconds because the only verb was
`show model`, one component per process; and a materialized dataset could not say which run
wrote it although the run knew at registration. One-shape campaign Step 5, M5e.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from vqapr.cli.main import main

_MODELS = """from vqapr import authoring as va

class Reads(va.DataModel):
    def inputs(self):
        return {"prices": va.DatasetInput(
            dataset_id='price_daily', fields=('close',), lookback=va.RowsLookback(rows=2)
        )}

    def compute(self, context):
        window = context.read("prices", "close")
        return [{"instrument": name, "score": 1.0} for name in window.instruments]


class ReadsNothingHere(va.DataModel):
    def inputs(self):
        return {"other": va.DatasetInput(
            dataset_id='elsewhere', fields=('x',), lookback=va.RowsLookback(rows=1)
        )}

    def compute(self, context):
        return []
"""


def _cli(capsys: pytest.CaptureFixture[str], project: Path, *argv: str) -> tuple[int, dict]:
    code = main(["--project-root", str(project), *argv])
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _prices(root: Path) -> Path:
    parquet = root / "price_daily.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', 100.0),
              (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', 103.0),
              (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'A', 105.0)
            ) AS t(available_at, instrument, close))
            TO '{parquet.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    return parquet


def _execution(root: Path) -> Path:
    parquet = root / "execution.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true, 100.0),
              (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 103.0)
            ) AS t(trade_at, instrument, is_tradable, close))
            TO '{parquet.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    return parquet


def _declaration(root: Path) -> Path:
    models = root / "models.py"
    models.write_text(_MODELS, encoding="utf-8")
    path = root / "declaration.yaml"
    path.write_text(
        f"""datasets:
  price_daily:
    source_id: prices
    path: {_prices(root).as_posix()}
    instrument_field: instrument
    available_at: available_at
    grain: instrument_instant
    key_fields: [available_at, instrument]
    fields:
      close: close
execution_inputs:
  krx-daily:
    table:
      source_id: execution
      path: {_execution(root).as_posix()}
      trade_at_field: trade_at
      instrument_field: instrument
      is_tradable_field: is_tradable
      price_fields:
        close: close
    fill:
      selector: same_day
      at: "15:30"
      timezone: Asia/Seoul
      trade_price: close
components:
  reads:
    kind: datamodel
    path: {models.as_posix()}
    object_name: Reads
  reads-nothing-here:
    kind: datamodel
    path: {models.as_posix()}
    object_name: ReadsNothingHere
runs:
  alpha:
    instruments: [A]
    start: "2024-03-06T00:00:00+09:00"
    end: "2024-03-08T00:00:00+09:00"
    sessions_from: price_daily
    timezone: Asia/Seoul
    at: "16:00"
    datamodels:
      reads:
        dataset_id: alpha_values
        value_fields: [score]
""",
        encoding="utf-8",
    )
    return path


def test_register_says_what_each_pit_bearing_declaration_means_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, registered = _cli(capsys, tmp_path, "register", str(_declaration(tmp_path)))

    assert code == 0, registered
    spoken = registered["spoken"]
    # One dataset sentence, two execution-input sentences (the table's clock; the fill, whose
    # four fields mean nothing apart), one run sentence. Nothing for the components: they carry
    # no point-in-time field of their own.
    assert len(spoken) == 4, spoken
    dataset, clock, fill, run = spoken
    assert dataset.startswith("dataset 'price_daily':") and "'available_at'" in dataset
    assert "never earlier" in dataset
    assert clock.startswith("execution input 'krx-daily':") and "'trade_at'" in clock
    assert fill.startswith("execution input 'krx-daily':")
    for word in ("same_day", "15:30:00", "Asia/Seoul", "'close'"):
        assert word in fill, (word, fill)
    assert run.startswith("run 'alpha':") and "16:00:00 Asia/Seoul" in run
    assert "knowable before" in run


def test_a_declaration_with_no_pit_field_says_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    models = tmp_path / "models.py"
    models.write_text(_MODELS, encoding="utf-8")
    declaration = tmp_path / "components.yaml"
    declaration.write_text(
        f"components:\n  reads:\n    kind: datamodel\n    path: {models.as_posix()}\n"
        "    object_name: Reads\n",
        encoding="utf-8",
    )

    code, registered = _cli(capsys, tmp_path, "register", str(declaration))

    assert code == 0, registered
    assert registered["spoken"] == [], "or nothing -- the rule's other half"


def test_a_materialized_dataset_names_the_run_that_wrote_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = _cli(capsys, tmp_path, "register", str(_declaration(tmp_path)))
    assert code == 0
    code, ran = _cli(capsys, tmp_path, "run", "alpha")
    assert code == 0, ran

    code, shown = _cli(capsys, tmp_path, "show", "dataset", "alpha_values")
    assert code == 0, shown
    assert shown["produced_by"] == "alpha", "known at registration; a fact, not a guess"

    code, mine = _cli(capsys, tmp_path, "show", "dataset", "price_daily")
    assert code == 0, mine
    assert mine["produced_by"] is None, "a dataset from the author's own file names no run"

    code, listed = _cli(capsys, tmp_path, "list", "datasets")
    by_id = {row["dataset_id"]: row for row in listed["items"]}
    assert by_id["alpha_values"]["produced_by"] == "alpha"
    assert "produced_by" not in by_id["price_daily"]


def test_list_components_can_be_asked_who_reads_a_dataset_in_one_process(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = _cli(capsys, tmp_path, "register", str(_declaration(tmp_path)))
    assert code == 0

    code, readers = _cli(capsys, tmp_path, "list", "components", "--reads", "price_daily")

    assert code == 0, readers
    assert [row["component_id"] for row in readers["items"]] == ["reads"]
    assert readers["items"][0]["reads"] == {"price_daily": ["close"]}
    assert readers["count"] == 1

    code, nobody = _cli(capsys, tmp_path, "list", "components", "--reads", "unheard-of")
    assert code == 0 and nobody["count"] == 0

    code, refused = _cli(capsys, tmp_path, "list", "runs", "--reads", "price_daily")
    assert code != 0
    assert refused["failures"][0]["code"] == "argument.value_invalid"
