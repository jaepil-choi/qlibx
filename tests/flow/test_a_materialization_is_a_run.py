"""A materialization writes a run record, so one `list runs` and one `show run` cover both kinds.

Owner ruling, record `116`. A materialization already produced exactly the facts a run record
carries — which declarations produced it, how many rows, over what window — and wrote them to
`.lineage.json`, **a file `list runs` does not index and `show run` cannot read**. The same question
had two answers in two formats, and one of them was invisible to both commands.

`.lineage.json` is still written for one release, with its per-invocation block demoted to a
*projection* of the record's `period` so the two cannot drift. Retiring it is a separate
owner-gated decision and is not this story.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vqapr.cli.show import record_view
from vqapr.flow.materialize import (
    MaterializationInvocation,
    _lineage_payload,
    _materialization_period,
    _materialization_run_id,
    _write_materialization_record,
)
from vqapr.flow.run_records import (
    MATERIALIZATION_KIND,
    RUN_KIND,
    read_record,
    record_fields,
    run_ids,
)


class _Registration:
    """The two fields the record builder reads, without constructing a full registration."""

    def __init__(self, dataset: str) -> None:
        self.dataset_id = dataset


def _invocation(day: int, rows: int) -> MaterializationInvocation:
    moment = datetime(2026, 4, day, 9, 0, tzinfo=UTC)
    return MaterializationInvocation(
        evaluation_time=moment,
        output_available_at=moment,
        row_count=rows,
        accesses=(),
    )


def _write(tmp_path: Path, dataset: str = "factor.value") -> Path:
    written = _write_materialization_record(
        project_root=tmp_path,
        registration=_Registration(dataset),  # type: ignore[arg-type]
        source_id="materialized-factor.value",
        component_fingerprint="f" * 64,
        invocations=(_invocation(1, 10), _invocation(2, 12)),
    )
    assert written is not None, "the product path must produce a record"
    return written


def test_a_materialization_lands_in_the_same_place_runs_do(tmp_path: Path) -> None:
    """The whole point: `list runs` finds it, because it is a run record in the runs directory."""
    _write(tmp_path)

    ids = run_ids(tmp_path)

    assert len(ids) == 1
    assert ids[0].startswith("materialize-factor.value-")


def test_the_record_declares_the_materialization_kind(tmp_path: Path) -> None:
    """A reader must be able to tell the two apart without inferring it from the id."""
    path = _write(tmp_path)
    body = json.loads(path.read_text(encoding="utf-8"))

    assert body["kind"] == MATERIALIZATION_KIND
    assert body["kind"] != RUN_KIND


def test_show_run_projects_it_through_the_materialization_fields(tmp_path: Path) -> None:
    """One `show run` covers both kinds, which is what record 115's discriminator was for.

    Through a run's field set this would have rendered six nulls and dropped everything it answers.
    """
    _write(tmp_path)
    record = read_record(tmp_path, run_ids(tmp_path)[0])

    view = record_view(record)

    assert view["kind"] == MATERIALIZATION_KIND
    assert view["dataset_id"] == "factor.value"
    assert view["rows"] == 22, "10 + 12 rows across two invocations"
    assert "account" not in view, "a materialization has no account"
    assert "tables" not in view


def test_every_declared_field_is_answered(tmp_path: Path) -> None:
    """The guarantee record 115 gave the run kind, held for this one too.

    A field named without a builder, or a builder without a field, must fail at the write rather
    than produce a record quietly missing an answer.
    """
    _write(tmp_path)
    record = read_record(tmp_path, run_ids(tmp_path)[0])

    for field in record_fields(MATERIALIZATION_KIND):
        assert field in record, f"{field} is declared for this kind and was not written"

    assert record["span"] == {
        "first": "2026-04-01T09:00:00+00:00",
        "last": "2026-04-02T09:00:00+00:00",
    }


def test_the_lineage_file_is_a_projection_of_the_record(tmp_path: Path) -> None:
    """Dual-written for one release, and structurally unable to drift.

    `.lineage.json` used to build its `invocations` block itself, so the record and the lineage file
    were two computations of the same facts. It reads the record's own structure now — the same
    argument record 112 makes about a second entry point growing its own copy.
    """
    invocations = (_invocation(1, 10), _invocation(2, 12))

    payload = _lineage_payload(
        component_id="value",
        fingerprint="f" * 64,
        source_id="materialized-factor.value",
        spec=_Spec(),  # type: ignore[arg-type]
        instruments=("A", "B"),
        invocations=invocations,
    )

    assert payload["invocations"] == _materialization_period(invocations)["invocations"]


class _Spec:
    dataset_id = "factor.value"
    value_fields = ("value",)


def test_a_rerun_of_the_same_window_replaces_rather_than_accumulates(tmp_path: Path) -> None:
    """Two materializations of the same dataset over the same times ARE the same run.

    A wall-clock id would make every invocation unique and turn `list runs` into a log of every
    time anyone rebuilt a dataset, which is not what a reader is asking when they list runs.
    """
    first = _materialization_run_id("factor.value", (_invocation(1, 10), _invocation(2, 12)))
    again = _materialization_run_id("factor.value", (_invocation(1, 99), _invocation(2, 99)))
    later = _materialization_run_id("factor.value", (_invocation(1, 10), _invocation(3, 12)))

    assert first == again, "the same window is the same run, whatever the row counts came out as"
    assert first != later, "a different window is a different run"


def test_a_record_failure_does_not_discard_a_completed_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1's lesson, applied before it can happen here.

    By the time the record is written the dataset is registered and the parquet is on disk.
    Refusing over the bookkeeping would discard completed work, which is the defect record 113
    fixed on the run path and must not be reintroduced on this one.
    """
    import vqapr.flow.materialize as materialize

    class _Exploding:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def open(self) -> None:
            raise OSError("the runs directory is not writable")

        def release(self) -> None:
            pass

    monkeypatch.setattr(materialize, "RunRecordWriter", _Exploding)

    written = materialize._write_materialization_record(
        project_root=tmp_path,
        registration=_Registration("factor.value"),  # type: ignore[arg-type]
        source_id="materialized-factor.value",
        component_fingerprint="f" * 64,
        invocations=(_invocation(1, 10),),
    )

    assert written is None, "the failure is absorbed and reported as no record, not raised"
