"""A DataModel is run as a registered run: the same loop, the same record, a dataset as output.

Record `148` (campaign Step 7, M2) closes `docs/issues/059`. `materialize()` ran a DataModel through
a loop of its own -- every row of every evaluation in memory until the end, one parquet and a
per-instrument lineage file at once, a record of its own kind that `show run` projected through a
special case. A datamodel run now goes through `preflight_run` and `orchestration.run` like a
strategy run: the sessions are the run's, each session's rows leave the process as one chunk, the
dataset registers once after the last session, and `runs/<run-id>/datamodels/<id>@<fp8>/` holds
the record.

The tests here pin what the old path published (the rows, computed by hand from the fixture now
that `materialize()` is gone) and what the new one promises beyond it: chunks that survive a
kill, a record without lineage, a refusal before the second run wastes the hour, memory that
lives across sessions, and workers under `--jobs`.
"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.data.datasets import DatasetRegistration
from vqapr.domain.shapes import Grain
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import MAX_EXAMPLES, Stage, Status, VqaprError
from vqapr.flow.datamodel import DataModelResult, output_directory, output_source_id
from vqapr.flow.judgments import judgments
from vqapr.flow.orchestration import RunResult, run
from vqapr.flow.preflight import preflight_run
from vqapr.flow.record import (
    _DATAMODEL_FIELDS,
    DATAMODEL_KIND,
    datamodel_refs,
    read_datamodel_record,
    read_run_record,
    strategy_refs,
)
from vqapr.flow.run import DataModelEntry, RunDefinition
from vqapr.public import register_data_model, register_dataset, register_run
from vqapr.workspace import WORKSPACE_DIRECTORY, Workspace

KST = ZoneInfo("Asia/Seoul")
START = datetime(2024, 3, 6, tzinfo=KST)
END = datetime(2024, 3, 8, tzinfo=KST)
SESSIONS = (datetime(2024, 3, 6, 16, tzinfo=KST), datetime(2024, 3, 7, 16, tzinfo=KST))
"""The two sessions inside `[START, END]` at 16:00: exactly the instants `materialize()` was
given before record `148` retired it, so the rows it published are the rows expected here."""

EXPECTED_ROWS = (
    (SESSIONS[0], "A", -(103.0 / 100.0 - 1.0)),
    (SESSIONS[0], "B", -(51.0 / 50.0 - 1.0)),
    (SESSIONS[1], "A", -(105.0 / 103.0 - 1.0)),
    (SESSIONS[1], "B", -(53.0 / 51.0 - 1.0)),
)
"""The reversal by hand from `model_price_parquet`: closes A 100, 103, 105 and B 50, 51, 53 on
3/5-3/7 at 15:30, a 2-row window at 16:00 on 3/6 and 3/7, `-(last / first - 1)`. The fixture's
3/8 row (close 999) is after both sessions; a score that used it would be nowhere near these."""

_MODELS = '''from pathlib import Path
from vqapr import authoring as va

WATCHED = Path(__WATCHED__)

class ReversalModel(va.DataModel):
    def inputs(self):
        return {"prices": va.DatasetInput(
            dataset_id='price_daily', fields=('close',), lookback=va.RowsLookback(rows=2)
        )}

    def compute(self, context):
        assert not hasattr(context, "account")
        assert not hasattr(context, "execution_table")
        window = context.read("prices", "close")
        by_instrument = {
            name: [float(v) for v in window.values[name] if v is not None]
            for name in window.instruments
        }
        return tuple(
            {"instrument": instrument, "score": -(values[-1] / values[0] - 1.0)}
            for instrument, values in sorted(by_instrument.items())
            if len(values) == 2
        )

class MomentumModel(ReversalModel):
    def compute(self, context):
        return tuple({**row, "score": -row["score"]} for row in super().compute(context))

class ForgingModel(ReversalModel):
    def compute(self, context):
        rows = super().compute(context)
        return tuple({**row, "available_at": context.evaluation_time} for row in rows)

class FailingSecondModel(ReversalModel):
    def compute(self, context):
        if context.evaluation_time.day == 7:
            raise RuntimeError("intentional second-session failure")
        return super().compute(context)

STRAY = tuple("X%02d" % n for n in range(20))
REPEATED = tuple("D%02d" % n for n in range(20))

class StrayNameModel(ReversalModel):
    def compute(self, context):
        rows = super().compute(context)
        stray = tuple({"instrument": name, "score": 0.0} for name in STRAY)
        return rows + stray + ({"instrument": STRAY[0], "score": 1.0},)

class RepeatedNameModel(ReversalModel):
    def compute(self, context):
        rows = tuple({"instrument": name, "score": 0.0} for name in REPEATED)
        return rows + rows

class ChunkWatcherModel(va.DataModel):
    """Reports how many chunks the output directory held when this session was computed."""

    def inputs(self):
        return {"prices": va.DatasetInput(
            dataset_id='price_daily', fields=('close',), lookback=va.RowsLookback(rows=1)
        )}

    def compute(self, context):
        landed = len(list(WATCHED.glob("*.parquet")))
        window = context.read("prices", "close")
        return [{"instrument": name, "chunks": landed} for name in sorted(window.instruments)]

class CountingModel(va.DataModel):
    """Counts its own calls in `memory` and emits the count, so the rows say what it remembered."""

    def inputs(self):
        return {"prices": va.DatasetInput(
            dataset_id='price_daily', fields=('close',), lookback=va.RowsLookback(rows=1)
        )}

    def compute(self, context):
        calls = dict(self.memory or {}).get("calls", 0) + 1
        self.memory = {"calls": calls}
        window = context.read("prices", "close")
        return [{"instrument": name, "calls": calls} for name in sorted(window.instruments)]

class EchoModel(va.DataModel):
    """Reads the dataset the reversal run wrote, the way any next model would."""

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
'''
"""Every DataModel these tests run; `__WATCHED__` is filled with the chunk watcher's directory."""


def _register_prices(project: Path, parquet: Path) -> None:
    register_dataset(
        project,
        DatasetRegistration.of(
            "price_daily",
            "prices",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields={"close": "close", "volume": "volume"},
            field_types={"close": "DOUBLE", "volume": "DOUBLE"},
        ),
        SourceSpec.of("prices", parquet),
    )


def _models(project: Path) -> Path:
    path = project / "models.py"
    watched = repr(output_directory(project, "watched").as_posix())
    path.write_text(_MODELS.replace("__WATCHED__", watched), encoding="utf-8")
    return path


def _definition(
    run_id: str,
    *entries: DataModelEntry,
    instruments: tuple[str, ...] = ("A", "B"),
    sessions_from: str = "price_daily",
    at: time = time(16, 0),
) -> RunDefinition:
    return RunDefinition(
        run_id=run_id,
        strategies=(),
        datamodels=entries,
        instruments=instruments,
        timezone="Asia/Seoul",
        at=at,
        sessions_from=sessions_from,
        start=START,
        end=END,
    )


def _store(project: Path) -> Path:
    return project / WORKSPACE_DIRECTORY


def _run(project: Path, definition: RunDefinition, *, jobs: int = 1) -> RunResult:
    """Preflight and run one definition against the project, recording under the store."""
    frozen = preflight_run(project, definition)
    return run(project, frozen, store_root=_store(project), jobs=jobs)


def _dataset_ids(project: Path) -> set[str]:
    return {str(item.dataset_id) for item in Workspace.open(project).datasets}


def _query(sql: str) -> list[tuple]:
    con = duckdb.connect()
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def _parquet(project: Path, dataset_id: str) -> str:
    """The duckdb expression reading every chunk of one output dataset."""
    return f"read_parquet('{output_directory(project, dataset_id).as_posix()}/*.parquet')"


def _chunks(project: Path, dataset_id: str) -> list[Path]:
    return sorted(output_directory(project, dataset_id).glob("*.parquet"))


def _prepared(project: Path, parquet: Path, *components: tuple[str, str]) -> None:
    """Prices registered, the model file written, and the named components registered."""
    _register_prices(project, parquet)
    source = _models(project)
    for component_id, object_name in components:
        register_data_model(project, component_id, source, object_name)


def _by_day(project: Path, dataset_id: str, field: str) -> list[tuple]:
    return _query(
        f"SELECT CAST(available_at AS DATE), instrument, {field} "
        f"FROM {_parquet(project, dataset_id)} ORDER BY 1, 2"
    )


def test_a_datamodel_run_publishes_the_rows_materialize_published(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """The output is the same dataset, reached through registration and through a read.

    The rows are `EXPECTED_ROWS`, worked by hand from the fixture: the same four rows
    `materialize()` published, with the point-in-time proof inside them -- the fixture's 3/8 row
    (close 999) sits after both sessions and reaches no score. The dataset registers once, after
    the last session, as a directory source of grain `instrument_instant`; and it is read the way
    any next model reads: a second datamodel run takes its sessions from it and echoes the value
    back.
    """
    _prepared(tmp_path, model_price_parquet, ("reversal", "ReversalModel"), ("echo", "EchoModel"))

    outcome = _run(
        tmp_path, _definition("factors", DataModelEntry("reversal", "reversal_2d", ("score",)))
    )

    result = outcome.result("reversal")
    assert isinstance(result, DataModelResult)
    assert result.rows == 4
    assert [trace.evaluation_time for trace in result.occurrences] == list(SESSIONS)
    workspace = Workspace.open(tmp_path)
    registration = workspace.dataset("reversal_2d")
    assert registration == result.registration
    assert str(registration.source) == output_source_id("reversal_2d")
    assert registration.grain is Grain.INSTRUMENT_INSTANT
    assert workspace.source(output_source_id("reversal_2d")).path == result.output_path
    assert result.output_path == output_directory(tmp_path, "reversal_2d")
    published = _query(
        "SELECT CAST(available_at AS TIMESTAMPTZ), instrument, score "
        f"FROM {_parquet(tmp_path, 'reversal_2d')} ORDER BY 1, 2"
    )
    assert len(published) == len(EXPECTED_ROWS)
    for (available_at, instrument, score), expected in zip(published, EXPECTED_ROWS, strict=True):
        assert (available_at, instrument) == expected[:2]
        assert score == pytest.approx(expected[2])

    echoed = _run(
        tmp_path,
        _definition(
            "echoes",
            DataModelEntry("echo", "echo_2d", ("echo",)),
            sessions_from="reversal_2d",
            at=time(16, 30),
        ),
    )

    assert "echo_2d" in _dataset_ids(tmp_path)
    assert echoed.result("echo").rows == 4
    assert _by_day(tmp_path, "echo_2d", "echo") == _by_day(tmp_path, "reversal_2d", "score"), (
        "what the next model read is what the first one wrote"
    )


def test_the_output_lands_as_one_file_when_the_dataset_registers(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """Sessions stay in memory and land once, at registration (`docs/issues/087`).

    The model itself counts the files in its output directory at compute time: both sessions
    see an empty directory, and the finished dataset is one `all.parquet`.
    """
    _prepared(tmp_path, model_price_parquet, ("watcher", "ChunkWatcherModel"))

    _run(tmp_path, _definition("watch", DataModelEntry("watcher", "watched", ("chunks",))))

    assert [path.name for path in _chunks(tmp_path, "watched")] == ["all.parquet"]
    assert not list(output_directory(tmp_path, "watched").glob(".*.tmp")), "staging is moved away"
    assert _by_day(tmp_path, "watched", "chunks") == [
        (date(2024, 3, 6), "A", 0),
        (date(2024, 3, 6), "B", 0),
        (date(2024, 3, 7), "A", 0),
        (date(2024, 3, 7), "B", 0),
    ]


def test_a_compute_failure_leaves_no_output_and_registers_nothing(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """A failed datamodel run leaves nothing readable: a partial dataset registers with nothing,
    so nothing is written for it (`087`), and the workspace never learns of it."""
    _prepared(tmp_path, model_price_parquet, ("failing", "FailingSecondModel"))
    before = Workspace.open(tmp_path).path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        _run(tmp_path, _definition("partial", DataModelEntry("failing", "partial", ("score",))))

    assert caught.value.stage is Stage.RUN
    assert caught.value.mutation is False
    (failure,) = caught.value.failures
    assert failure.code == "datamodel.compute_failed"
    assert failure.status is Status.CRASHED, "the user's own compute raised"
    assert failure.cause is not None and failure.cause.origin == "user"
    assert (failure.cause.traceback or "").startswith("Traceback")
    assert "intentional second-session failure" in failure.observed
    assert _chunks(tmp_path, "partial") == []
    assert "partial" not in _dataset_ids(tmp_path)
    assert Workspace.open(tmp_path).path.read_bytes() == before


@pytest.mark.parametrize(
    ("component", "object_name", "instruments", "code", "example_total", "examples", "observed"),
    [
        (
            "forger",
            "ForgingModel",
            ("A", "B"),
            "datamodel.output.available_at_owned",
            0,
            (),
            "row 0 ",
        ),
        (
            "stray",
            "StrayNameModel",
            ("A", "B"),
            "datamodel.output.instrument_unrequested",
            20,
            tuple(f"X{n:02d}" for n in range(MAX_EXAMPLES)),
            "20 unrequested instrument(s) across 21 of 23 output row(s)",
        ),
        (
            "repeated",
            "RepeatedNameModel",
            tuple(f"D{n:02d}" for n in range(20)),
            "datamodel.output.instrument_duplicate",
            20,
            tuple(f"D{n:02d}" for n in range(MAX_EXAMPLES)),
            "20 repeated instrument(s) across 20 extra of 40 output row(s)",
        ),
    ],
)
def test_an_output_breach_is_refused_by_its_code_and_registers_nothing(
    tmp_path: Path,
    model_price_parquet: Path,
    component: str,
    object_name: str,
    instruments: tuple[str, ...],
    code: str,
    example_total: int,
    examples: tuple[str, ...],
    observed: str,
) -> None:
    """The output contract moved with the loop and kept its codes under the new stage.

    A forged `available_at` is structural and stops at the first row, quoting no value: an empty
    `examples` beside `example_total: 0` is the honest answer there. Unrequested and duplicated
    instruments are content breaches, collected before truncation (issue 032): twenty offenders
    on purpose, because a single one cannot tell fail-fast from collect-then-report, and the
    stray fixture emits one name twice so the distinct count (20) and the row count (21) differ.
    """
    _prepared(tmp_path, model_price_parquet, (component, object_name))
    before = Workspace.open(tmp_path).path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        _run(
            tmp_path,
            _definition(
                "breach",
                DataModelEntry(component, "breached", ("score",)),
                instruments=instruments,
            ),
        )

    assert caught.value.stage is Stage.RUN
    assert caught.value.mutation is False
    (failure,) = caught.value.failures
    assert failure.code == code
    assert failure.example_total == example_total
    assert len(failure.examples) == min(example_total, MAX_EXAMPLES)
    assert failure.examples == examples, "each offender quoted once, in first-seen order"
    assert failure.observed.startswith(observed)
    assert "breached" not in _dataset_ids(tmp_path)
    assert Workspace.open(tmp_path).path.read_bytes() == before


def test_the_record_is_one_line_per_session_and_no_lineage(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """`datamodel.json` answers what the dataset cannot, and nothing `059` measured at 478 MB.

    The record names the component registered and as loaded, the dataset and its fields, and one
    entry per session with when it evaluated, when its rows became available and how many. No
    per-instrument lineage, no tables. `run.json` lists the datamodel with its dataset, and the
    strategy side of the same run is empty.
    """
    _prepared(tmp_path, model_price_parquet, ("reversal", "ReversalModel"))
    definition = _definition("factors", DataModelEntry("reversal", "reversal_2d", ("score",)))
    ref = preflight_run(tmp_path, definition).datamodel("reversal").record_ref

    outcome = _run(tmp_path, definition)

    store = _store(tmp_path)
    assert datamodel_refs(store, "factors") == (ref,)
    assert strategy_refs(store, "factors") == ()
    record = read_datamodel_record(store, "factors", ref)
    assert outcome.records["reversal"] == record
    assert set(_DATAMODEL_FIELDS) <= set(record), sorted(set(_DATAMODEL_FIELDS) - set(record))
    assert record["kind"] == DATAMODEL_KIND
    assert record["run_id"] == "factors"
    assert record["datamodel_ref"] == ref
    assert record["datamodel_id"] == "reversal"
    assert record["dataset_id"] == "reversal_2d"
    assert record["value_fields"] == ["score"]
    assert record["rows"] == 4
    assert record["source_digest"] == {"reversal": record["fingerprint"]}
    assert record["period"]["occurrences"] == 2
    assert len(record["sessions"]) == 2
    for session in record["sessions"]:
        assert set(session) == {"evaluation_time", "output_available_at", "row_count"}
        assert session["row_count"] == 2
    assert "invocations" not in record
    directory = store / "runs" / "factors" / "datamodels" / ref
    assert (directory / "datamodel.json").is_file()
    assert list(directory.glob("*.parquet")) == [], "a datamodel's rows are its dataset, not tables"
    run_json = read_run_record(store, "factors")
    assert run_json["datamodels"] == [
        {"component_id": "reversal", "record": ref, "dataset_id": "reversal_2d"}
    ]
    assert run_json["strategies"] == []
    assert run_json["exchange"] is None and run_json["execution"] is None


def test_a_second_run_is_refused_before_it_computes(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """The output's name is taken; preflight says so, and `check` asks the same question."""
    _prepared(tmp_path, model_price_parquet, ("reversal", "ReversalModel"))
    definition = _definition("factors", DataModelEntry("reversal", "reversal_2d", ("score",)))
    _run(tmp_path, definition)
    chunks_before = _chunks(tmp_path, "reversal_2d")

    with pytest.raises(VqaprError) as refused:
        preflight_run(tmp_path, definition)

    assert refused.value.stage is Stage.FREEZE
    assert refused.value.mutation is False
    (failure,) = refused.value.failures
    assert failure.code == "datamodel.output_registered"
    assert failure.status is Status.CONFLICT
    assert "reversal_2d" in failure.observed
    found, blocked = judgments(definition, Workspace.open(tmp_path))
    assert blocked == []
    assert [item.code for item in found] == ["datamodel.output_registered"]
    assert found[0].source is not None
    assert found[0].source.key_path == "runs.factors.datamodels.reversal.dataset_id"
    assert _chunks(tmp_path, "reversal_2d") == chunks_before, "the refusal touches no chunk"


def test_jobs_runs_each_datamodel_in_a_worker_and_both_register(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """Two datamodels, two workers, two datasets; the results come back as records.

    A worker freezes the REGISTERED run again, so the definition is registered first; the
    in-process `results` are empty and `records` carries what each worker wrote.
    """
    _prepared(
        tmp_path, model_price_parquet, ("reversal", "ReversalModel"), ("momentum", "MomentumModel")
    )
    definition = _definition(
        "factors",
        DataModelEntry("reversal", "reversal_2d", ("score",)),
        DataModelEntry("momentum", "momentum_2d", ("score",)),
    )
    assert register_run(tmp_path, definition) is True

    outcome = _run(tmp_path, definition, jobs=2)

    assert dict(outcome.results) == {}
    assert set(outcome.records) == {"reversal", "momentum"}
    assert {"reversal_2d", "momentum_2d"} <= _dataset_ids(tmp_path)
    assert set(datamodel_refs(_store(tmp_path), "factors")) == {
        outcome.records["reversal"]["datamodel_ref"],
        outcome.records["momentum"]["datamodel_ref"],
    }
    for component_id, dataset_id in (("reversal", "reversal_2d"), ("momentum", "momentum_2d")):
        assert outcome.records[component_id]["dataset_id"] == dataset_id
        assert outcome.records[component_id]["rows"] == 4
        assert [path.name for path in _chunks(tmp_path, dataset_id)] == ["all.parquet"]
    opposite = _query(
        f"SELECT max(abs(r.score + m.score)) FROM {_parquet(tmp_path, 'reversal_2d')} r "
        f"JOIN {_parquet(tmp_path, 'momentum_2d')} m USING (available_at, instrument)"
    )
    assert opposite[0][0] == pytest.approx(0.0)


def test_a_worker_refusal_comes_back_as_the_same_error_the_sequential_loop_raises(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """A datamodel refused in a `--jobs` worker is refused by its own code in the parent.

    The strategy pool learned this in `docs/issues/073` by returning an outcome; the datamodel
    pool was a copy that never did, so a `VqaprError` raised in a worker failed to unpickle
    (keyword-only constructor) and the run died as `stage: unhandled` with no failures. One pool
    driver for both kinds and a picklable `VqaprError` close it (record `170`).
    """
    _prepared(
        tmp_path, model_price_parquet, ("reversal", "ReversalModel"), ("stray", "StrayNameModel")
    )
    definition = _definition(
        "factors",
        DataModelEntry("reversal", "reversal_2d", ("score",)),
        DataModelEntry("stray", "stray_2d", ("score",)),
    )
    assert register_run(tmp_path, definition) is True

    with pytest.raises(VqaprError) as caught:
        _run(tmp_path, definition, jobs=2)

    assert caught.value.stage is Stage.RUN
    (failure,) = caught.value.failures
    assert failure.code == "datamodel.output.instrument_unrequested"
    assert "stray_2d" not in _dataset_ids(tmp_path)


def test_memory_persists_across_the_sessions_of_one_run(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """One instance for the whole run: what session one remembered, session two sees.

    The opening memory is the entry's own declaration, so a second run starts from what it says
    rather than from nothing.
    """
    _prepared(tmp_path, model_price_parquet, ("counter", "CountingModel"))

    _run(tmp_path, _definition("counted", DataModelEntry("counter", "counted", ("calls",))))
    _run(
        tmp_path,
        _definition(
            "resumed",
            DataModelEntry("counter", "resumed", ("calls",), initial_model_memory={"calls": 10}),
        ),
    )

    for dataset_id, expected in (("counted", (1, 2)), ("resumed", (11, 12))):
        assert _by_day(tmp_path, dataset_id, "calls") == [
            (date(2024, 3, 6), "A", expected[0]),
            (date(2024, 3, 6), "B", expected[0]),
            (date(2024, 3, 7), "A", expected[1]),
            (date(2024, 3, 7), "B", expected[1]),
        ]


def test_an_edited_component_computes_and_the_record_says_what_loaded(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """Editing a registered component and re-running is the ordinary development loop.

    This once pinned the opposite: an edit was refused at load with
    `component.load.fingerprint_drift`, whose stated repair -- re-register -- the registry then
    refused in turn (`docs/implementations/057`). The gate went (issue 009) and the fingerprint
    became a receipt: the record carries the registered fingerprint and, per component, the one
    that actually loaded, so the edit neither refuses nor mints a second identity.
    """
    _prepared(tmp_path, model_price_parquet, ("reversal", "ReversalModel"))
    (registered,) = Workspace.open(tmp_path).components
    source = tmp_path / "models.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")

    outcome = _run(
        tmp_path, _definition("drifted", DataModelEntry("reversal", "drifted", ("score",)))
    )

    after = Workspace.open(tmp_path)
    assert [str(ref.component_id) for ref in after.components] == ["reversal"], (
        "an edit must not mint a second component id"
    )
    assert after.dataset("drifted") is not None
    record = outcome.records["reversal"]
    assert record["fingerprint"] == registered.fingerprint
    assert record["source_digest"]["reversal"] != registered.fingerprint, (
        "the record names the bytes that ran, not the bytes that were registered"
    )
