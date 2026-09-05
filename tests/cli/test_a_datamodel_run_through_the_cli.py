"""A datamodel run through the verbs a user types: register, check, run, list, show, rm.

Record `148` (campaign Step 7, M2). Before it a DataModel was run from a spec file `run` alone
accepted, with its own `check` phases and its own success envelope. It is a `runs:` entry now, so
every verb that knows a run knows a datamodel run: `check` judges it and preflights it, `run`
executes it under `--jobs`, `list datasets` shows what it wrote, `show run` reads the record that
says which datamodel wrote which dataset, and a second `check` refuses the name that is taken.

M3 gave the datamodel record its own readers, mirroring the strategy record's: `list datamodels
--run`, `show datamodel <run-id>/<id>@<fp8>` (the short form when unique), and `rm datamodel`,
which removes the record and only the record -- the dataset it registered is what other runs may
already read.
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


def test_a_datamodel_record_is_listed_shown_and_removed_by_its_own_verbs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The record a datamodel writes is readable by name, the way a strategy's is.

    Before M3 the only readback was `show run`, which lists every member, and `list datasets`,
    which says nothing about which run wrote what. A reader with two fingerprints of one model
    needs the record itself -- rows, sessions, the frozen component -- and needs to be able to
    retire one without touching the dataset the other still reads.
    """
    project = ("--project-root", str(tmp_path))
    store = tmp_path / ".vqapr"
    code, registered = _cli(capsys, *project, "register", str(_declaration(tmp_path)))
    assert code == 0, registered
    code, ran = _cli(capsys, *project, "run", "factors")
    assert code == 0, ran
    reversal_ref = ran["datamodels"]["reversal"]["record"]
    momentum_ref = ran["datamodels"]["momentum"]["record"]
    fp8 = reversal_ref.split("@", 1)[1]

    # `list datamodels --run`: one row per record, carrying what it wrote and when.
    code, listed = _cli(capsys, *project, "list", "datamodels", "--run", "factors")
    assert code == 0, listed
    assert listed["kind"] == "datamodels" and listed["count"] == 2
    rows = {row["datamodel_ref"]: row for row in listed["items"]}
    assert set(rows) == {reversal_ref, momentum_ref}
    row = rows[reversal_ref]
    assert row["run_id"] == "factors"
    assert row["datamodel_id"] == "reversal"
    assert row["fingerprint"].startswith(fp8), "the ref's fp8 is the fingerprint's head"
    assert row["dataset_id"] == "reversal_2d"
    assert row["rows"] == 4
    assert row["period"]["occurrences"] == 2

    # The filters are the strategy list's: by model id, by fingerprint prefix, by period end.
    code, by_id = _cli(
        capsys, *project, "list", "datamodels", "--run", "factors", "--strategy", "reversal"
    )
    assert [row["datamodel_ref"] for row in by_id["items"]] == [reversal_ref]
    code, by_fp = _cli(
        capsys, *project, "list", "datamodels", "--run", "factors", "--fingerprint", fp8
    )
    assert [row["datamodel_ref"] for row in by_fp["items"]] == [reversal_ref]
    code, later = _cli(
        capsys, *project, "list", "datamodels", "--run", "factors",
        "--since", "2030-01-01T00:00:00+09:00",
    )
    assert code == 0 and later["count"] == 0, later
    code, no_run = _cli(capsys, *project, "list", "datamodels")
    assert code == 1, no_run
    assert no_run["failures"][0]["code"] == "cli.input.value_invalid"
    assert "list datamodels --run" in no_run["failures"][0]["fix"]

    # `show datamodel`: the full form and the short form answer the same record, and the answer
    # is the record's own field set -- a field written and never surfaced would fail here.
    from vqapr.flow.run_records import read_datamodel_record

    frozen = read_datamodel_record(store, "factors", reversal_ref)
    for identifier in (f"factors/{reversal_ref}", "factors/reversal"):
        code, shown = _cli(capsys, *project, "show", "datamodel", identifier)
        assert code == 0, shown
        assert shown["stage"] == "datamodel.show"
        assert shown["kind"] == "datamodel"
        assert shown["run_id"] == "factors"
        assert shown["datamodel_ref"] == reversal_ref
        assert shown["datamodel_id"] == "reversal"
        assert shown["dataset_id"] == "reversal_2d"
        assert shown["value_fields"] == ["score"]
        assert shown["rows"] == 4
        assert len(shown["sessions"]) == 2, "one entry per session it evaluated"
        # `workspace_root` is every envelope's, not the record's (`docs/issues/066`).
        envelope = {key for key in shown if key not in {"ok", "stage", "kind", "workspace_root"}}
        assert envelope == set(frozen) - {"schema", "kind"}, (
            f"record-only={sorted(set(frozen) - {'schema', 'kind'} - envelope)}, "
            f"surfaced-only={sorted(envelope - set(frozen))}"
        )

    # A datamodel has no tables of its own: its rows ARE the dataset, and `--table` is refused
    # pointing at the verb that reads a dataset rather than answering with an empty table list.
    code, refused = _cli(
        capsys, *project, "show", "datamodel", "factors/reversal", "--table", "vqapr.account"
    )
    assert code == 1, refused
    detail = refused["failures"][0]
    assert detail["code"] == "cli.input.value_invalid"
    assert "reversal_2d" in detail["observed"]
    assert "vqapr show dataset reversal_2d" in detail["fix"]

    # A ref the run does not hold is refused naming the refs it does hold.
    code, unknown = _cli(capsys, *project, "show", "datamodel", "factors/nope")
    assert code == 1, unknown
    assert reversal_ref in unknown["failures"][0]["observed"]
    assert "list datamodels --run" in unknown["failures"][0]["fix"]
    code, bare = _cli(capsys, *project, "show", "datamodel", "reversal")
    assert code == 1 and "<run-id>/<datamodel-id>@<fp8>" in bare["failures"][0]["requirement"]

    # `rm datamodel` removes the record and nothing else: the dataset stays registered and its
    # rows stay on disk, because a record is what a run wrote about itself and a dataset is what
    # other runs may already read.
    code, removed = _cli(capsys, *project, "rm", "datamodel", "factors/reversal")
    assert code == 0, removed
    assert removed["stage"] == "record.removed"
    assert removed["kind"] == "datamodel"
    assert removed["run_id"] == "factors"
    assert removed["removed"] == [reversal_ref]

    code, remaining = _cli(capsys, *project, "list", "datamodels", "--run", "factors")
    assert [row["datamodel_ref"] for row in remaining["items"]] == [momentum_ref]
    # `show run` answers from the frozen `run.json`, which still says the run WROTE both -- that
    # is history, and removing a record does not rewrite it -- while `recorded` says what the
    # store holds now.
    code, shown_run = _cli(capsys, *project, "show", "run", "factors")
    assert {item["record"] for item in shown_run["datamodels"]} == {reversal_ref, momentum_ref}
    assert shown_run["recorded"] == [momentum_ref]
    code, datasets = _cli(capsys, *project, "list", "datasets")
    assert "reversal_2d" in {row["dataset_id"] for row in datasets["items"]}, (
        "removing a record unregistered the dataset it wrote"
    )
    assert len(_scores(tmp_path, "reversal_2d")) == 4, "the rows outlive the record"
    code, again = _cli(capsys, *project, "rm", "datamodel", "factors/reversal")
    assert code == 1, "a record already removed is refused, not removed twice"
    assert again["failures"][0]["code"] == "cli.input.value_invalid"
