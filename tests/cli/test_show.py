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

from vqapr.cli.list_ import run as list_run
from vqapr.cli.show import record_view
from vqapr.cli.show import run as show_run
from vqapr.flow.record import RunRecordWriter, read_record
from vqapr.inputs import InputError

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
    # `kind` is the discriminator record `115` added. It is projected in addition to the field set,
    # not as a member of it: a record's kind decides WHICH field set applies, so putting it inside
    # one of them would make it a fact about runs rather than about records.
    assert set(record_view({})) == {*RECORD_FIELDS, "kind"}, (
        "the reader projects a different field set than the one both sides are built from"
    )
    assert record_view({})["kind"] == "run", (
        "a record with no discriminator predates one, and every such record is a run"
    )

    # The strategy record (record 139) answers what a run record answered before -- the account,
    # the tables, the contract, the roster, the period, the digests -- plus what architecture
    # §17.3.2 found missing: which `.py` ran, under which agenda and constraints, and the
    # strategy's own fingerprint. Pinned the same way, so a builder added to `_freeze_strategy`
    # without a field here is caught at the writer.
    from vqapr.cli.show import STRATEGY_FIELDS

    assert set(STRATEGY_FIELDS) == {
        "run_id",
        "strategy_ref",
        "strategy_id",
        "fingerprint",
        "component",
        "agenda",
        "constraints",
        "account",
        "tables",
        "contract",
        "source_digest",
        "declared_digest",
        "roster",
        "period",
        # Seconds by phase (`docs/issues/068`): where the run's wall clock went.
        "timing",
    }
    assert set(record_view({"kind": "strategy"})) == {*STRATEGY_FIELDS, "kind"}

    # The datamodel record (record 148) is the third kind, read by `show datamodel`. It answers
    # what it wrote -- the dataset, its fields, its row count, one entry per session -- and not
    # an account, tables, a contract or constraints, none of which a datamodel has.
    from vqapr.cli.show import DATAMODEL_FIELDS

    assert set(DATAMODEL_FIELDS) == {
        "run_id",
        "datamodel_ref",
        "datamodel_id",
        "fingerprint",
        "component",
        "agenda",
        "dataset_id",
        "value_fields",
        "rows",
        "sessions",
        "source_digest",
        "declared_digest",
        "period",
    }
    assert set(record_view({"kind": "datamodel"})) == {*DATAMODEL_FIELDS, "kind"}


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


_STRATEGY_RECORD = {
    **_RECORD,
    "strategy_id": "s",
    "fingerprint": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
}


def _strategy_store(root: Path, run_id: str, rows: list[dict]) -> str:
    """One finished strategy record under a run, written the way a run writes it."""
    writer = RunRecordWriter(root, run_id, "s@abcdef01")
    writer.open()
    writer.append("vqapr.account", rows)
    writer.finish(_STRATEGY_RECORD, kind="strategy")
    return "s@abcdef01"


def test_list_strategies_finds_the_record_by_scanning(tmp_path: Path) -> None:
    """AC-P1. No index file exists to read, which is the design rather than an omission.

    `list runs` lists REGISTERED runs since record 139; what the store holds is a strategy record
    under a run, and `list strategies --run <id>` finds it by scanning the run's directory.
    """
    ref = _strategy_store(tmp_path, "alpha", [{"instrument": "_ACCOUNT", "nav": "1000"}])

    payload = list_run(
        argparse.Namespace(kind="strategies", identifier=None, store_root=tmp_path, run_id="alpha"),
        project_root=tmp_path,
    )

    assert payload["count"] == 1
    row = payload["items"][0]
    assert row["run_id"] == "alpha"
    assert row["strategy_ref"] == ref
    assert row["strategy_id"] == "s"
    assert row["fingerprint"] == _STRATEGY_RECORD["fingerprint"]
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


def test_show_strategy_table_filters_by_instrument(tmp_path: Path) -> None:
    """A6: the NAV series of a 2.6M-row account table is one call, not a bypass of the surface.

    The tables belong to the strategy record since record 139, so the reader is `show strategy
    <run>/<strategy-ref> --table`; the short form `<run>/<strategy-id>` resolves when the run
    holds one record of that strategy.
    """
    ref = _strategy_store(
        tmp_path,
        "wide",
        [
            {"instrument": "_ACCOUNT", "nav": "1000"},
            {"instrument": "A005930", "nav": None},
            {"instrument": "A000660", "nav": None},
            {"instrument": "_ACCOUNT", "nav": "1010"},
        ],
    )

    for identifier in (f"wide/{ref}", "wide/s"):
        payload = show_run(
            argparse.Namespace(
                kind="strategy",
                identifier=identifier,
                store_root=tmp_path,
                table="vqapr.account",
                limit=0,
                instrument="_ACCOUNT",
            ),
            project_root=tmp_path,
        )

        assert payload["stage"] == "strategy.table"
        assert payload["strategy_ref"] == ref
        assert payload["rows_total"] == 4
        assert payload["matched"] == 2
        assert payload["returned"] == 2
        assert [row["nav"] for row in payload["items"]] == ["1000", "1010"]

