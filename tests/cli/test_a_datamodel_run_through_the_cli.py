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
import os
import time
from pathlib import Path

import duckdb
import pytest

import vqapr.cli.run as run_command
from vqapr.cli.main import main
from vqapr.data import store as store_module
from vqapr.flow import orchestration
from vqapr.flow.orchestration import batch_cubes, in_workers, run_registered_datamodel
from vqapr.project.store import Workspace

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
            f"""COPY (SELECT available_at, instrument, close::DOUBLE AS close FROM (VALUES
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
    field_types:
      close: DOUBLE
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
  factors-reversal:
    instruments: [A, B]
    start: "2024-03-06T00:00:00+09:00"
    end: "2024-03-08T00:00:00+09:00"
    timezone: Asia/Seoul
    agenda: {{every: 1d, at: "16:00", days_from: price_daily}}
    datamodels:
      reversal:
        dataset_id: reversal_2d
        value_fields: [score]
  factors-momentum:
    instruments: [A, B]
    start: "2024-03-06T00:00:00+09:00"
    end: "2024-03-08T00:00:00+09:00"
    timezone: Asia/Seoul
    agenda: {{every: 1d, at: "16:00", days_from: price_daily}}
    datamodels:
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
    assert sorted(registered["registered"]["runs"]) == ["factors-momentum", "factors-reversal"]
    assert set(registered["registered"]["components"]) == {"reversal", "momentum"}

    code, checked = _cli(capsys, *project, "check", "factors-reversal")
    assert code == 0, checked
    assert checked["ok"] is True
    assert checked["blocked"] == []
    assert checked["checked"] == ["workspace", "run", "judgments", "preflight"]
    assert checked["passed"] == checked["checked"], "every phase, the datamodel ones included"

    # Two models is two runs (design §2.3), and naming both is one invocation.
    code, ran = _cli(capsys, *project, "run", "factors-reversal", "factors-momentum")
    assert code == 0, ran
    assert set(ran["runs"]) == {"factors-reversal", "factors-momentum"}
    lines: dict[str, dict] = {}
    for run_id, component_id, dataset_id in (
        ("factors-reversal", "reversal", "reversal_2d"),
        ("factors-momentum", "momentum", "momentum_2d"),
    ):
        entry = ran["runs"][run_id]
        assert entry["stage"] == "run.complete"
        assert entry["run_id"] == run_id
        assert "strategies" not in entry, "a datamodel run reports datamodels, not strategies"
        assert set(entry["datamodels"]) == {component_id}
        line = entry["datamodels"][component_id]
        assert line["dataset_id"] == dataset_id
        assert line["rows"] == 4
        assert line["sessions"] == 2
        assert line["record"].startswith(f"{component_id}@")
        lines[component_id] = line
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
    assert {(row["run_id"], row["kind"]) for row in runs["items"]} == {
        ("factors-reversal", "datamodel"),
        ("factors-momentum", "datamodel"),
    }

    code, shown = _cli(capsys, *project, "show", "run", "factors-reversal")
    assert code == 0, shown
    assert shown["kind"] == "run"
    assert shown["strategies"] == []
    assert {(item["component_id"], item["dataset_id"]) for item in shown["datamodels"]} == {
        ("reversal", "reversal_2d")
    }
    assert {item["record"] for item in shown["datamodels"]} == {lines["reversal"]["record"]}
    assert shown["exchange"] is None and shown["execution"] is None

    # The names are this run's own now (design §2.1): `check` still passes -- a run's earlier
    # product is state, not a defect of the declaration -- and running again without `--force`
    # is refused before anything is computed, the way a standing record is.
    code, again = _cli(capsys, *project, "check", "factors-reversal")
    assert code == 0, again
    assert again["ok"] is True and again["passed"] == again["checked"]

    code, refused = _cli(capsys, *project, "run", "factors-reversal")
    assert code == 1, refused
    assert refused["ok"] is False
    codes = [failure["code"] for failure in refused["failures"]]
    assert codes == ["run.output_registered"], codes
    assert all(failure["status"] == 409 for failure in refused["failures"]), refused["failures"]
    assert "--force" in refused["failures"][0]["fix"]
    assert _scores(tmp_path, "reversal_2d") == reversal, "refused before it wrote anything"

    code, replaced = _cli(capsys, *project, "run", "factors-reversal", "--force")
    assert code == 0, replaced
    assert _scores(tmp_path, "reversal_2d") == reversal, "withdrawn and published afresh"

    # `rm dataset` is not the retry (`docs/issues/090`): with the dataset gone and the component
    # file unchanged, the record of the same fingerprint still stands, and the run is refused as
    # a 409 at stage `record` that names the model's own kind and `--force` -- not a 400 that
    # said "edit the strategy" to a datamodel run and carried a FileExistsError traceback.
    code, dropped = _cli(capsys, *project, "rm", "dataset", "reversal_2d")
    assert code == 0, dropped
    code, standing = _cli(capsys, *project, "run", "factors-reversal")
    assert code == 1, standing
    assert standing["stage"] == "record"
    (failure,) = standing["failures"]
    assert failure["code"] == "record.exists" and failure["status"] == 409
    assert failure["requirement"] == "a datamodel record is written once per run and fingerprint"
    assert "strategy" not in failure["requirement"] + failure["fix"]
    assert "vqapr run factors-reversal --force" in failure["fix"]
    assert failure["cause"]["traceback"] is None, "a routine refusal carries no traceback"
    code, again = _cli(capsys, *project, "run", "factors-reversal", "--force")
    assert code == 0, again
    assert _scores(tmp_path, "reversal_2d") == reversal


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
    code, ran = _cli(capsys, *project, "run", "factors-reversal")
    assert code == 0, ran
    reversal_ref = ran["datamodels"]["reversal"]["record"]
    code, ran_momentum = _cli(capsys, *project, "run", "factors-momentum")
    assert code == 0, ran_momentum
    momentum_ref = ran_momentum["datamodels"]["momentum"]["record"]
    fp8 = reversal_ref.split("@", 1)[1]

    # `list datamodels --run`: one row per record, carrying what it wrote and when.
    code, listed = _cli(capsys, *project, "list", "datamodels", "--run", "factors-reversal")
    assert code == 0, listed
    assert listed["kind"] == "datamodels" and listed["count"] == 1
    rows = {row["datamodel_ref"]: row for row in listed["items"]}
    assert set(rows) == {reversal_ref}
    code, momentum_listed = _cli(
        capsys, *project, "list", "datamodels", "--run", "factors-momentum"
    )
    assert code == 0 and {row["datamodel_ref"] for row in momentum_listed["items"]} == {
        momentum_ref
    }, "each run's record is listed under its own run id"
    row = rows[reversal_ref]
    assert row["run_id"] == "factors-reversal"
    assert row["datamodel_id"] == "reversal"
    assert row["fingerprint"].startswith(fp8), "the ref's fp8 is the fingerprint's head"
    assert row["dataset_id"] == "reversal_2d"
    assert row["rows"] == 4
    assert row["period"]["occurrences"] == 2

    # The filters are the strategy list's: by model id, by fingerprint prefix, by period end.
    code, by_id = _cli(
        capsys,
        *project,
        "list",
        "datamodels",
        "--run",
        "factors-reversal",
        "--strategy",
        "reversal",
    )
    assert [row["datamodel_ref"] for row in by_id["items"]] == [reversal_ref]
    code, by_fp = _cli(
        capsys, *project, "list", "datamodels", "--run", "factors-reversal", "--fingerprint", fp8
    )
    assert [row["datamodel_ref"] for row in by_fp["items"]] == [reversal_ref]
    code, later = _cli(
        capsys,
        *project,
        "list",
        "datamodels",
        "--run",
        "factors-reversal",
        "--since",
        "2030-01-01T00:00:00+09:00",
    )
    assert code == 0 and later["count"] == 0, later
    code, no_run = _cli(capsys, *project, "list", "datamodels")
    assert code == 1, no_run
    assert no_run["failures"][0]["code"] == "argument.value_invalid"
    assert "list datamodels --run" in no_run["failures"][0]["fix"]

    # `show datamodel`: the full form and the short form answer the same record, and the answer
    # is the record's own field set -- a field written and never surfaced would fail here.
    from vqapr.record import read_datamodel_record

    frozen = read_datamodel_record(store, "factors-reversal", reversal_ref)
    for identifier in (f"factors-reversal/{reversal_ref}", "factors-reversal/reversal"):
        code, shown = _cli(capsys, *project, "show", "datamodel", identifier)
        assert code == 0, shown
        assert shown["stage"] == "datamodel.show"
        assert shown["kind"] == "datamodel"
        assert shown["run_id"] == "factors-reversal"
        assert shown["datamodel_ref"] == reversal_ref
        assert shown["datamodel_id"] == "reversal"
        assert shown["dataset_id"] == "reversal_2d"
        assert shown["value_fields"] == ["score"]
        assert shown["rows"] == 4
        assert len(shown["sessions"]) == 2, "one entry per session it evaluated"
        # `workspace_root` is every envelope's, not the record's (`docs/issues/archive/066`).
        envelope = {key for key in shown if key not in {"ok", "stage", "kind", "workspace_root"}}
        assert envelope == set(frozen) - {"schema", "kind"}, (
            f"record-only={sorted(set(frozen) - {'schema', 'kind'} - envelope)}, "
            f"surfaced-only={sorted(envelope - set(frozen))}"
        )

    # A datamodel has no tables of its own: its rows ARE the dataset, and `--table` is refused
    # pointing at the verb that reads a dataset rather than answering with an empty table list.
    code, refused = _cli(
        capsys,
        *project,
        "show",
        "datamodel",
        "factors-reversal/reversal",
        "--table",
        "vqapr.account",
    )
    assert code == 1, refused
    detail = refused["failures"][0]
    assert detail["code"] == "argument.value_invalid"
    assert "reversal_2d" in detail["observed"]
    assert "vqapr show dataset reversal_2d" in detail["fix"]

    # A ref the run does not hold is refused naming the refs it does hold.
    code, unknown = _cli(capsys, *project, "show", "datamodel", "factors-reversal/nope")
    assert code == 1, unknown
    assert reversal_ref in unknown["failures"][0]["observed"]
    assert "list datamodels --run" in unknown["failures"][0]["fix"]
    code, bare = _cli(capsys, *project, "show", "datamodel", "reversal")
    assert code == 1 and "<run-id>/<datamodel-id>@<fp8>" in bare["failures"][0]["requirement"]

    # `rm datamodel` removes the record and nothing else: the dataset stays registered and its
    # rows stay on disk, because a record is what a run wrote about itself and a dataset is what
    # other runs may already read.
    code, removed = _cli(capsys, *project, "rm", "datamodel", "factors-reversal/reversal")
    assert code == 0, removed
    assert removed["stage"] == "record.removed"
    assert removed["kind"] == "datamodel"
    assert removed["run_id"] == "factors-reversal"
    assert removed["removed"] == [reversal_ref]

    code, remaining = _cli(capsys, *project, "list", "datamodels", "--run", "factors-reversal")
    assert remaining["items"] == [], "the run's one record is gone"
    code, other = _cli(capsys, *project, "list", "datamodels", "--run", "factors-momentum")
    assert [row["datamodel_ref"] for row in other["items"]] == [momentum_ref], (
        "removing one run's record leaves another run's alone"
    )
    # `show run` answers from the frozen `run.json`, which still says the run WROTE it -- that
    # is history, and removing a record does not rewrite it -- while `recorded` says what the
    # store holds now.
    code, shown_run = _cli(capsys, *project, "show", "run", "factors-reversal")
    assert {item["record"] for item in shown_run["datamodels"]} == {reversal_ref}
    assert shown_run["recorded"] == []
    code, datasets = _cli(capsys, *project, "list", "datasets")
    assert "reversal_2d" in {row["dataset_id"] for row in datasets["items"]}, (
        "removing a record unregistered the dataset it wrote"
    )
    assert len(_scores(tmp_path, "reversal_2d")) == 4, "the rows outlive the record"
    code, again = _cli(capsys, *project, "rm", "datamodel", "factors-reversal/reversal")
    assert code == 1, "a record already removed is refused, not removed twice"
    assert again["failures"][0]["code"] == "argument.value_invalid"


_ECHO = """from vqapr import authoring as va

class EchoModel(va.DataModel):
    def inputs(self):
        return {"scores": va.DatasetInput(
            dataset_id='reversal_2d', fields=('score',), lookback=va.RowsLookback(rows=1)
        )}

    def compute(self, context):
        window = context.read("scores", "score")
        return [
            {"instrument": name, "echo": float(window.values[name][-1])}
            for name in sorted(window.instruments)
            if window.values[name] and window.values[name][-1] is not None
        ]
"""


def _echo_declaration(root: Path) -> Path:
    """A third datamodel that reads what the reversal run wrote, declared once it exists."""
    models = root / "echo.py"
    models.write_text(_ECHO, encoding="utf-8")
    path = root / "echo.yaml"
    path.write_text(
        f"""components:
  echo:
    kind: datamodel
    path: {models.as_posix()}
    object_name: EchoModel
runs:
  factors-echo:
    instruments: [A, B]
    start: "2024-03-06T00:00:00+09:00"
    end: "2024-03-08T00:00:00+09:00"
    timezone: Asia/Seoul
    agenda: {{every: 1d, at: "16:00", days_from: price_daily}}
    datamodels:
      echo:
        dataset_id: echo_2d
        value_fields: [echo]
""",
        encoding="utf-8",
    )
    return path


def test_jobs_spreads_datamodel_runs_and_refuses_a_batch_that_depends_on_itself(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`vqapr run a b --jobs 2` puts datamodel runs in the pool, and says so.

    `docs/issues/report-2026-09-10-run-jobs-does-not-parallelise-datamodel-runs.md`: from record
    `201` the CLI put only strategy runs in the pool and ran datamodel runs one at a time in this
    process, whatever `--jobs` said; a 671-run sweep on 32 cores took eight hours instead of
    forty minutes, and nothing in the envelope said the pool was not there. Three things are
    pinned here: the datamodel runs reach `in_workers` in one call and the envelope's `jobs`
    says how many processes ran them; a refusal raised inside a worker (a standing record) is
    that run's own 409 entry, rendered exactly as the sequential path renders it, beside the
    other run's; and a batch in which one run reads what another writes is refused whole
    before anything is spawned (owner decision 2026-09-10).
    """
    project = ("--project-root", str(tmp_path))
    code, registered = _cli(capsys, *project, "register", str(_declaration(tmp_path)))
    assert code == 0, registered

    pooled: list[list[str]] = []

    def spy(run_ids, *args, **kwargs):
        pooled.append(list(run_ids))
        return in_workers(run_ids, *args, **kwargs)

    monkeypatch.setattr(run_command, "in_workers", spy)

    code, ran = _cli(capsys, *project, "run", "factors-reversal", "factors-momentum", "--jobs", "2")
    assert code == 0, ran
    assert ran["ok"] is True and ran["jobs"] == 2
    assert pooled == [["factors-reversal", "factors-momentum"]], "both went to one pool"
    for run_id, dataset_id in (
        ("factors-reversal", "reversal_2d"),
        ("factors-momentum", "momentum_2d"),
    ):
        entry = ran["runs"][run_id]
        assert entry["ok"] is True and entry["stage"] == "run.complete"
        assert entry["writes"] == dataset_id
        (block,) = entry["datamodels"].values()
        assert block["dataset_id"] == dataset_id and block["rows"] == 4
        assert "strategies" not in entry
    assert sorted(_scores(tmp_path, "reversal_2d")) == sorted(
        (day, name, -score) for day, name, score in _scores(tmp_path, "momentum_2d")
    )
    cubes = tmp_path / ".vqapr" / "cubes"
    assert cubes.is_dir() and not any(cubes.iterdir()), "the batch's cubes are gone with it"

    # The same batch again, no --force: each worker raises `RunRecordExists`, and each run's
    # entry is the 409 the sequential path gives -- not one exception for the batch, and not
    # a bare `error` string.
    code, standing = _cli(
        capsys, *project, "run", "factors-reversal", "factors-momentum", "--jobs", "2"
    )
    assert code == 1 and standing["ok"] is False and standing["jobs"] == 2
    assert len(pooled) == 2
    for run_id in ("factors-reversal", "factors-momentum"):
        entry = standing["runs"][run_id]
        assert entry["ok"] is False and entry["stage"] == "record"
        (failure,) = entry["failures"]
        assert failure["code"] == "record.exists" and failure["status"] == 409
        assert (
            failure["requirement"] == "a datamodel record is written once per run and fingerprint"
        )
        assert f"vqapr run {run_id} --force" in failure["fix"]

    # A reader of `reversal_2d` can be registered now that the dataset exists. Named in one
    # batch with its writer, the batch is refused before a process is spawned.
    code, registered = _cli(capsys, *project, "register", str(_echo_declaration(tmp_path)))
    assert code == 0, registered
    code, refused = _cli(
        capsys, *project, "run", "factors-reversal", "factors-echo", "--jobs", "2", "--force"
    )
    assert code == 1 and refused["ok"] is False
    assert refused["stage"] == "check" and "runs" not in refused
    (failure,) = refused["failures"]
    assert failure["code"] == "run.batch_dependent" and failure["status"] == 400
    assert (
        "'factors-echo' reads 'reversal_2d', which 'factors-reversal' writes" in failure["observed"]
    )
    assert failure["fix"].startswith("vqapr run factors-reversal first")
    assert len(pooled) == 2, "nothing was spawned"
    code, datasets = _cli(capsys, *project, "list", "datasets")
    assert code == 0 and "echo_2d" not in {row["dataset_id"] for row in datasets["items"]}

    # Run in the graph's order, the same two runs are fine: the writer alone, then its reader.
    code, echoed = _cli(capsys, *project, "run", "factors-echo", "--jobs", "2")
    assert code == 0, echoed
    assert echoed["ok"] is True and "jobs" not in echoed, "one run keeps its own envelope"


def test_a_jobs_batch_bakes_once_maps_in_every_worker_and_leaves_nothing_behind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`docs/issues/098`, record `236`: the driver bakes what the batch reads, a worker maps it.

    Before, every worker scanned the same parquet into a panel of its own -- 671 scans of one
    430 MB file for a 671-run sweep, and twelve private copies beside twelve interpreters. Now
    `batch_cubes` scans each panel-grain dataset once into `.vqapr/cubes/<batch>/`, the worker
    takes its panel from the memory-mapped files without a scan, and the directory is removed
    when the batch returns -- on success, on an exception, and (by the next batch) after a hard
    kill left one behind. Nothing accumulates (owner decision 2026-09-10).
    """
    project = ("--project-root", str(tmp_path))
    code, registered = _cli(capsys, *project, "register", str(_declaration(tmp_path)))
    assert code == 0, registered
    workspace = Workspace.open(tmp_path)
    root = tmp_path / ".vqapr" / "cubes"

    scanned: list[dict[str, object]] = []
    original = store_module.scan.observation_table

    def counting(spec, **kwargs):
        scanned.append(dict(kwargs))
        return original(spec, **kwargs)

    monkeypatch.setattr(store_module.scan, "observation_table", counting)

    with batch_cubes(workspace, ["factors-reversal", "factors-momentum"]) as cubes:
        assert cubes is not None and cubes.parent == root
        assert (cubes / "batch.lock").is_file()
        assert (cubes / "price_daily" / "close.npy").is_file(), "the one dataset both runs read"
        assert scanned[-1]["instruments"] is None, "baked over every instrument"
        baked = len(scanned)
        assert baked == 1
        # The worker, in this process: its panel comes from the cube, so it scans nothing.
        record = run_registered_datamodel(
            str(tmp_path), "factors-reversal", str(tmp_path / ".vqapr"), True, str(cubes)
        )
        assert record["dataset_id"] == "reversal_2d" and record["rows"] == 4
        assert len(scanned) == baked, "the worker built its panel from the cube"
    assert not cubes.exists(), "removed when the batch returned"
    assert sorted(_scores(tmp_path, "reversal_2d"))[0][1] == "A"

    # A batch that dies still removes its directory.
    with (
        pytest.raises(RuntimeError, match="the pool died"),
        batch_cubes(workspace, ["factors-reversal"]) as failing,
    ):
        raise RuntimeError("the pool died")
    assert not failing.exists()

    # A directory a hard-killed driver left behind is swept once its lock is stale; a live
    # batch's directory (a fresh lock) is not.
    stale = root / "1-dead"
    stale.mkdir()
    (stale / "batch.lock").write_text("1", encoding="ascii")
    old = time.time() - orchestration.CUBE_STALE_AFTER - 60
    os.utime(stale / "batch.lock", (old, old))
    live = root / "2-alive"
    live.mkdir()
    (live / "batch.lock").write_text("2", encoding="ascii")
    with batch_cubes(workspace, ["factors-momentum"]):
        assert not stale.exists() and live.exists()
    live_lock = live / "batch.lock"
    live_lock.unlink()
    live.rmdir()


def test_the_batch_driver_asks_each_run_what_it_reads_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record `238`: the independence judgment and the bake each loaded every component of the
    batch to ask what it reads (`experiments/exp_238`, `15_run_batch`: `_reads` x4 for two
    runs). The CLI asks once through `batch_reads` and hands the answer to both doors."""
    from vqapr.flow.orchestration import batch_reads, require_independent_batch

    project = ("--project-root", str(tmp_path))
    code, registered = _cli(capsys, *project, "register", str(_declaration(tmp_path)))
    assert code == 0, registered
    workspace = Workspace.open(tmp_path)
    targets = ["factors-reversal", "factors-momentum"]

    asked: list[str] = []
    original = orchestration._reads

    def counting(space, definition):
        asked.append(definition.run_id)
        return original(space, definition)

    monkeypatch.setattr(orchestration, "_reads", counting)

    reads = batch_reads(workspace, targets)
    assert set(reads) == set(targets)
    assert reads["factors-reversal"]["price_daily"] == {"close"}
    require_independent_batch(workspace, targets, reads)
    with batch_cubes(workspace, targets, reads) as cubes:
        assert cubes is not None and (cubes / "price_daily" / "close.npy").is_file()
    assert asked == targets, f"the batch asked its runs {len(asked)} times"

    # Without the answer handed in, each door still asks for itself.
    asked.clear()
    require_independent_batch(workspace, targets)
    with batch_cubes(workspace, targets):
        pass
    assert asked == targets * 2
