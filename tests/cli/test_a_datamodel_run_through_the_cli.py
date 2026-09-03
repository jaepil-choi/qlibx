"""A datamodel run through the verbs a user types: register, check, run, list, show, check again.

Record `148` (campaign Step 7, M2). Before it a DataModel was run from a spec file `run` alone
accepted, with its own `check` phases and its own success envelope. It is a `runs:` entry now, so
every verb that knows a run knows a datamodel run: `check` judges it and preflights it, `run`
executes it under `--jobs`, `list datasets` shows what it wrote, `show run` reads the record that
says which datamodel wrote which dataset, and a second `check` refuses the name that is taken.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from vqapr.cli.main import main

_MODELS = """from vqapr import authoring as va

class ReversalModel(va.DataModel):
    def inputs(self):
        return {"prices": va.DatasetInput(
            dataset_id='price_daily', fields=('close',), lookback=va.RowsLookback(rows=2)
        )}

    def compute(self, context):
        window = context.read("prices", "close")
        out = []
        for name in window.instruments:
            values = [float(v) for v in window.values[name] if v is not None]
            if len(values) == 2:
                out.append({"instrument": name, "score": -(values[-1] / values[0] - 1.0)})
        return out

class MomentumModel(ReversalModel):
    def compute(self, context):
        return [{**row, "score": -row["score"]} for row in super().compute(context)]
"""


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    """Run one command exactly as the console script would and parse its one JSON line."""
    code = main(argv)
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def _prices(root: Path) -> Path:
    """Two instruments over four sessions; the run's period admits the middle two."""
    parquet = root / "price_daily.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', 100.0),
              (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', 103.0),
              (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'A', 105.0),
              (TIMESTAMPTZ '2024-03-08 15:30:00+09', 'A', 110.0),
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B',  50.0),
              (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'B',  51.0),
              (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'B',  53.0),
              (TIMESTAMPTZ '2024-03-08 15:30:00+09', 'B',  52.0)
            ) AS t(available_at, instrument, close))
            TO '{parquet.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    return parquet


def _declaration(root: Path) -> Path:
    """The whole workspace as one file: the prices, two datamodels, the run computing both."""
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
components:
  reversal:
    kind: datamodel
    path: {models.as_posix()}
    object_name: ReversalModel
  momentum:
    kind: datamodel
    path: {models.as_posix()}
    object_name: MomentumModel
runs:
  factors:
    instruments: [A, B]
    start: "2024-03-06T00:00:00+09:00"
    end: "2024-03-08T00:00:00+09:00"
    sessions_from: price_daily
    timezone: Asia/Seoul
    at: "16:00"
    datamodels:
      reversal:
        dataset_id: reversal_2d
        value_fields: [score]
      momentum:
        dataset_id: momentum_2d
        value_fields: [score]
""",
        encoding="utf-8",
    )
    return path


def _scores(root: Path, dataset_id: str) -> list[tuple]:
    con = duckdb.connect()
    try:
        return con.execute(
            "SELECT CAST(available_at AS DATE), instrument, score FROM read_parquet("
            f"'{(root / '.vqapr' / 'materialized' / dataset_id).as_posix()}/*.parquet') "
            "ORDER BY 1, 2"
        ).fetchall()
    finally:
        con.close()


def test_a_datamodel_run_is_registered_checked_run_listed_and_shown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = ("--project-root", str(tmp_path))

    code, registered = _cli(capsys, *project, "register", str(_declaration(tmp_path)))
    assert code == 0, registered
    assert registered["registered"]["runs"] == ["factors"]
    assert set(registered["registered"]["components"]) == {"reversal", "momentum"}

    code, checked = _cli(capsys, *project, "check", "factors")
    assert code == 0, checked
    assert checked["ok"] is True
    assert checked["blocked"] == []
    assert checked["checked"] == ["workspace", "run", "judgments", "preflight"]
    assert checked["passed"] == checked["checked"], "every phase, the datamodel ones included"

    code, ran = _cli(capsys, *project, "run", "factors", "--jobs", "2")
    assert code == 0, ran
    assert ran["stage"] == "run.complete"
    assert ran["run_id"] == "factors"
    assert "strategies" not in ran, "a datamodel run reports datamodels, not strategies"
    assert set(ran["datamodels"]) == {"reversal", "momentum"}
    for component_id, dataset_id in (("reversal", "reversal_2d"), ("momentum", "momentum_2d")):
        line = ran["datamodels"][component_id]
        assert line["dataset_id"] == dataset_id
        assert line["rows"] == 4
        assert line["sessions"] == 2
        assert line["record"].startswith(f"{component_id}@")
    reversal, momentum = _scores(tmp_path, "reversal_2d"), _scores(tmp_path, "momentum_2d")
    assert [(day, name) for day, name, _ in reversal] == [(day, name) for day, name, _ in momentum]
    assert all(r[2] == pytest.approx(-m[2]) for r, m in zip(reversal, momentum, strict=True))

    # `list datasets` is the readback: the outputs are registered datasets like any other.
    code, datasets = _cli(capsys, *project, "list", "datasets")
    assert code == 0, datasets
    assert {row["dataset_id"] for row in datasets["items"]} == {
        "price_daily",
        "reversal_2d",
        "momentum_2d",
    }

    code, runs = _cli(capsys, *project, "list", "runs")
    assert code == 0, runs
    assert [(row["run_id"], row["kind"]) for row in runs["items"]] == [("factors", "datamodel")]

    code, shown = _cli(capsys, *project, "show", "run", "factors")
    assert code == 0, shown
    assert shown["kind"] == "run"
    assert shown["strategies"] == []
    assert {(item["component_id"], item["dataset_id"]) for item in shown["datamodels"]} == {
        ("reversal", "reversal_2d"),
        ("momentum", "momentum_2d"),
    }
    assert {item["record"] for item in shown["datamodels"]} == {
        line["record"] for line in ran["datamodels"].values()
    }
    assert shown["exchange"] is None and shown["execution_input"] is None

    # The names are taken now: `check` says so for each output, and preflight agrees.
    code, again = _cli(capsys, *project, "check", "factors")
    assert code == 1, again
    assert again["ok"] is False
    codes = [failure["code"] for failure in again["failures"]]
    assert codes.count("check.datamodel.output_registered") == 2
    assert {
        failure["source"]["key_path"]
        for failure in again["failures"]
        if failure["code"] == "check.datamodel.output_registered"
    } == {
        "runs.factors.datamodels.reversal.dataset_id",
        "runs.factors.datamodels.momentum.dataset_id",
    }
    assert "preflight.datamodel.output_registered" in codes
