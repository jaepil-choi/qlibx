"""The record carries a `kind`, and a reader that cannot understand it refuses loudly.

Record `115`. Before it, three things were true at once:

* `RECORD_FIELDS` was a flat 8-tuple, so the record could describe exactly one kind of thing;
* `read_record` was `json.loads` with **no schema branch at all**; and
* `cli/show.py` read every field with `record.get(field)`.

Together those meant a reverted reader handed a new-shape record did not refuse — it rendered the
fields it recognised and silently dropped the rest — and a new reader handed an old record rendered
the new fields as `null`, which is indistinguishable from "this run genuinely had none". "A reverted
reader refuses loudly" was an assumption, not a property.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vqapr.cli.show import record_view
from vqapr.flow.run_records import (
    MATERIALIZATION_KIND,
    RECORD_FIELDS,
    RUN_KIND,
    SCHEMA,
    RunRecordWriter,
    read_record,
    record_fields,
    record_path,
)


def _finished(tmp_path: Path, run_id: str = "r1") -> Path:
    writer = RunRecordWriter(tmp_path, run_id)
    writer.open()
    return writer.finish({field: None for field in RECORD_FIELDS if field != "run_id"})


def test_a_written_record_declares_its_schema_and_its_kind(tmp_path: Path) -> None:
    """Both, and the kind before the answers, so a reader knows what it holds."""
    path = _finished(tmp_path)
    body = json.loads(path.read_text(encoding="utf-8"))

    assert body["schema"] == SCHEMA
    assert body["kind"] == RUN_KIND


def test_a_reader_refuses_a_schema_from_the_future(tmp_path: Path) -> None:
    """The property that did not exist. A newer major must stop the reader, not be rendered.

    This is the point of the story: without it, a `vqapr` reverted to an older version reads a
    record whose fields may have been redefined and reports them as though it understood.
    """
    path = _finished(tmp_path)
    body = json.loads(path.read_text(encoding="utf-8"))
    body["schema"] = "vqapr-run-record/v9"
    path.write_text(json.dumps(body), encoding="utf-8")

    with pytest.raises(ValueError, match="does not understand") as refused:
        read_record(tmp_path, "r1")

    message = str(refused.value)
    assert "v9" in message, "the refusal must name the schema it found"
    assert SCHEMA in message, "and the one it reads, so the reader knows the gap"
    assert "Upgrade" in message, "and what to do about it"


def test_an_older_record_is_still_readable_and_is_a_run(tmp_path: Path) -> None:
    """`v1` predates the discriminator, and every `v1` record is a run by construction.

    A schema check that refused old records would make the bump a breaking change for every stored
    run, which is the opposite of what it is for.
    """
    path = _finished(tmp_path)
    body = json.loads(path.read_text(encoding="utf-8"))
    body["schema"] = "vqapr-run-record/v1"
    del body["kind"]
    path.write_text(json.dumps(body), encoding="utf-8")

    record = read_record(tmp_path, "r1")

    assert record["kind"] == RUN_KIND, "a record with no discriminator is a run"
    assert record_view(record)["kind"] == RUN_KIND


def test_a_record_that_is_not_a_mapping_is_named_rather_than_crashing_later(
    tmp_path: Path,
) -> None:
    """The shape check the schema check needs in front of it."""
    _finished(tmp_path)
    path = record_path(tmp_path, "r1")
    path.write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")

    with pytest.raises(ValueError, match="not a mapping"):
        read_record(tmp_path, "r1")


def test_the_field_set_is_chosen_by_kind() -> None:
    """The shape change itself: two kinds, two field sets, one discriminator."""
    assert record_fields(RUN_KIND) == RECORD_FIELDS
    assert record_fields(MATERIALIZATION_KIND) != RECORD_FIELDS
    assert "dataset_id" in record_fields(MATERIALIZATION_KIND)

    # The questions both kinds answer keep the same names, so a reader asking "which declarations
    # produced this" need not know which kind it is holding.
    shared = set(record_fields(RUN_KIND)) & set(record_fields(MATERIALIZATION_KIND))
    assert {"run_id", "source_digest", "declared_digest", "period"} <= shared


def test_an_unknown_kind_is_refused_at_both_ends(tmp_path: Path) -> None:
    """A `KeyError` here is the same deliberate guarantee the flat tuple gave.

    A builder named without a field, or a kind named without a field set, fails at the write rather
    than producing a record quietly missing its answers.
    """
    with pytest.raises(KeyError, match="unknown run-record kind"):
        record_fields("nonsense")

    writer = RunRecordWriter(tmp_path, "bad-kind")
    writer.open()
    with pytest.raises(KeyError, match="unknown run-record kind"):
        writer.finish({}, kind="nonsense")


def test_show_projects_a_materialization_through_its_own_fields() -> None:
    """Why the flat tuple could not survive a second kind.

    Projecting a materialization through a run's field list would render six nulls and drop
    everything it actually answers. Record `116` writes these; the projection is correct now so
    that story adds a producer rather than also changing the reader.
    """
    view = record_view({"kind": MATERIALIZATION_KIND, "dataset_id": "prices", "rows": 42})

    assert view["kind"] == MATERIALIZATION_KIND
    assert view["dataset_id"] == "prices"
    assert view["rows"] == 42
    assert "account" not in view, "a materialization has no account to report"
    assert "tables" not in view
