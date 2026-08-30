"""`vqapr show run <id>` answers from the frozen record, and answers the same thing it froze.

AC-R5 asks for two properties that sound like one. They are not.

**A cold process gets the same values.** Proved in `tests/flow/test_run_records.py` with real
spawned processes, because that is the only honest way to prove it.

**The output and the record carry the same field set.** Proved here, and proved structurally
rather than by example: one serializer produces both, so a field cannot be added to one and
forgotten in the other. A test that compared one run's output to one run's record would pass while
leaving that drift possible for every other run.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from vqapr.cli.inputs import InputError
from vqapr.cli.list_ import run as list_run
from vqapr.cli.show import record_view
from vqapr.cli.show import run as show_run
from vqapr.flow.run_records import RunRecordWriter, read_record

_RECORD = {
    "account": {"version": 7, "cash": "1000", "positions": {"A005930": "5"}},
    "tables": {"vqapr.account": {"rows": 12, "instants": 6}},
    "contract": {"accepted_intents": 7},
    "source_digest": "digest-abc",
    "declared_digest": "digest-abc",
    # What this run knew each instrument to be. `None` is the other legal value and says the run
    # never knew -- every fill then records `kind: None`, which is the state that used to be
    # indistinguishable from a categorised run.
    "roster": {
        "digest": "roster-digest-abc",
        "tables": ["etf", "stock"],
        "by_kind": {"stock": 10, "etf": 2},
        "instruments": 12,
    },
    "period": {"start": "2024-01-01", "end": "2024-12-31", "occurrences": 12},
}


@pytest.fixture
def store(tmp_path: Path) -> Path:
    writer = RunRecordWriter(tmp_path, "alpha")
    writer.open()
    writer.append("vqapr.account", [{"instrument": "_ACCOUNT", "nav": "1000"}])
    writer.finish(_RECORD)
    return tmp_path


def test_show_answers_every_question_the_record_holds(store: Path) -> None:
    """AC-P2: account, tables with counts, contract report, digest and derived period."""
    payload = show_run(
        argparse.Namespace(kind="run", identifier="alpha", store_root=store),
        project_root=store,
    )

    assert payload["ok"] is True
    assert payload["account"]["version"] == 7
    assert payload["tables"]["vqapr.account"] == {"rows": 12, "instants": 6}
    assert payload["contract"] == {"accepted_intents": 7}
    assert payload["source_digest"] == "digest-abc"
    assert payload["period"]["occurrences"] == 12


def test_the_output_and_the_record_carry_one_field_set(store: Path) -> None:
    """AC-R5's second half, checked against the RECORD rather than against the projection.

    The obvious version of this test is a tautology, and it shipped as one: comparing the envelope
    against `set(record_view(frozen))` compares `record_view`'s keys to a payload built FROM
    `record_view`, since `show_run`'s last line is `success(..., **record_view(...))` and `success`
    adds only `ok`/`stage`. It held for any implementation, including one returning nothing.

    Comparing against the frozen record's OWN keys is what makes it real: a field written to the
    record and never surfaced now fails here, which is the drift AC-R5 exists to prevent.
    """
    payload = show_run(
        argparse.Namespace(kind="run", identifier="alpha", store_root=store),
        project_root=store,
    )
    frozen = read_record(store, "alpha")

    envelope = {key for key in payload if key not in {"ok", "stage"}}
    # `schema` is the record's own metadata rather than one of its answers.
    assert envelope == set(frozen) - {"schema"}, (
        "the record and `show run` have drifted: "
        f"record-only={sorted(set(frozen) - {'schema'} - envelope)}, "
        f"surfaced-only={sorted(envelope - set(frozen))}"
    )


def test_a_field_written_to_the_record_but_never_surfaced_is_refused_at_the_writer() -> None:
    """The same guarantee at the other end, where it can be made structural.

    A test compares one example. The writer checks its payload against the same `RECORD_FIELDS`
    the reader projects, so the two cannot diverge for any record rather than merely this one.
    """
    from vqapr.cli.show import RECORD_FIELDS

    # `run_id` is stamped by the writer itself, so the payload it assembles carries the rest.
    assert set(RECORD_FIELDS) == {
        "run_id",
        "account",
        "tables",
        "contract",
        "source_digest",
        # Both had builders in `_freeze_record` and were absent from `RECORD_FIELDS`, so the
        # writer's comprehension never called them: computed on every run and dropped before
        # reaching disk.
        "declared_digest",
        "roster",
        "period",
    }
    assert set(record_view({})) == set(RECORD_FIELDS), (
        "the reader projects a different field set than the one both sides are built from"
    )


def test_showing_an_unknown_run_names_what_the_store_does_hold(store: Path) -> None:
    """A reader who mistypes an id needs the ids, not a stack trace."""
    with pytest.raises(InputError) as refused:
        show_run(
            argparse.Namespace(kind="run", identifier="typo", store_root=store),
            project_root=store,
        )

    body = refused.value.as_dict()
    assert "alpha" in (body["failures"][0]["observed"] or "")
    assert "list runs" in (body["retry_precondition"] or "")


def test_list_runs_finds_the_record_by_scanning(store: Path) -> None:
    """AC-P1. No index file exists to read, which is the design rather than an omission."""
    payload = list_run(
        argparse.Namespace(kind="runs", identifier=None, store_root=store),
        project_root=store,
    )

    assert payload["count"] == 1
    row = payload["items"][0]
    assert row["run_id"] == "alpha"
    assert row["account_version"] == 7
    assert row["tables"] == ["vqapr.account"]


def test_list_runs_reports_an_empty_store_rather_than_failing(tmp_path: Path) -> None:
    """"Nothing has run yet" is an answer this command can give, and often the first one asked."""
    payload = list_run(
        argparse.Namespace(kind="runs", identifier=None, store_root=tmp_path),
        project_root=tmp_path,
    )

    assert payload["ok"] is True
    assert payload["count"] == 0
