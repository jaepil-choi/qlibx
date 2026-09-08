"""A real run freezes real records, and a second run of one strategy refuses by name.

This path once shipped with no coverage at all. `public.run(store_root=...)` was never called from
any test, showcase or script, so `replace=`, `RunRecordExists`, the CLI's `--force` handler and
the record's drift guard were all live and unexercised.

The run here is the shipped sample journey, because a record is only worth freezing if a real run
produced it: a hand-built `SimulationResult` would exercise the writer while proving nothing about
what a run actually records. Two records since `139`: `run.json` and one `strategy.json`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import tests.sample.journey as journey
from vqapr.cli.show import RECORD_FIELDS, STRATEGY_FIELDS, record_view
from vqapr.flow.record import (
    RUN_JSON_FIELDS,
    RunRecordExists,
    read_run_record,
    read_strategy_record,
    run_ids,
    strategy_refs,
    table_ids,
)
from vqapr.public import FrozenRun, Workspace, preflight_run
from vqapr.public import run as execute_run


def _frozen(root: Path) -> FrozenRun:
    panel = journey.install(root)
    return preflight_run(root, journey.definition(panel))


@pytest.mark.slow
def test_a_run_freezes_records_a_later_process_could_read(tmp_path: Path) -> None:
    """AC-R3 end to end, from a real run rather than a constructed result."""
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "store"
    frozen = _frozen(project)

    outcome = execute_run(project, frozen, store_root=store)
    result = outcome.result()

    assert run_ids(store) == (journey.RUN_ID,)
    (ref,) = strategy_refs(store, journey.RUN_ID)
    record = read_strategy_record(store, journey.RUN_ID, ref)
    # The facts a later reader cannot reconstruct from the rows alone.
    assert record["account"]["version"] == result.final_state.account.snapshot.version
    assert record["tables"], "a run that recorded nothing would make the record pointless"
    assert record["source_digest"][journey.STRATEGY_ID]
    assert record["period"]["occurrences"] == len(result.occurrences)
    assert "contract" in record
    assert table_ids(store, journey.RUN_ID, ref), "the recorded tables sit beside the record"

    # A5: what the run wrote reads back as what it was. `nav` is a Decimal on the `_ACCOUNT`
    # row and `observed_at` an offset-aware instant, decoded by the sidecar the writer left.
    from decimal import Decimal

    from vqapr.public import read_strategy_table

    account_rows = [
        row
        for row in read_strategy_table(store, journey.RUN_ID, "vqapr.account", ref)
        if row["instrument"] == "_ACCOUNT"
    ]
    assert account_rows, "a real run values its book at least once"
    assert all(isinstance(row["nav"], Decimal) for row in account_rows)
    assert all(row["observed_at"].utcoffset() is not None for row in account_rows)


def test_a_store_may_keep_the_account_row_alone(tmp_path: Path) -> None:
    """`record_account_positions=False` -- cash and NAV per valuation, no per-instrument rows.

    The testbed's broad signed book wrote 2.6M position rows of which the rows actually read
    were the `_ACCOUNT` ones (0.07%). Fills are recorded either way.
    """
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "store"
    frozen = _frozen(project)

    execute_run(project, frozen, store_root=store, record_account_positions=False)

    from vqapr.flow.record import read_table

    (ref,) = strategy_refs(store, journey.RUN_ID)
    instruments = {
        row["instrument"] for row in read_table(store, journey.RUN_ID, "vqapr.account", ref)
    }
    assert instruments == {"_ACCOUNT"}, instruments
    assert "vqapr.fill" in table_ids(store, journey.RUN_ID, ref)


@pytest.mark.slow
def test_the_records_and_show_cannot_drift_apart(tmp_path: Path) -> None:
    """Each record and its `show` view read one field set, checked against REAL frozen records.

    The writers build their payloads by iterating the field sets, so a field named without a
    builder is a `KeyError` at the writer before anything reaches disk. The set equality below
    therefore holds by construction and is a smoke check; what this test is really worth is
    that it drives a REAL run, so it fails on any change to the shape of what a run records.
    """
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "store"
    execute_run(project, _frozen(project), store_root=store)

    run_record = read_run_record(store, journey.RUN_ID)
    assert set(run_record) - {"schema", "kind"} == set(RUN_JSON_FIELDS)
    assert set(record_view(run_record)) == {*RUN_JSON_FIELDS, "kind"}
    assert run_record["kind"] == "run"
    for field in RUN_JSON_FIELDS:
        if field != "monitoring":
            assert run_record[field] is not None, field

    (ref,) = strategy_refs(store, journey.RUN_ID)
    record = read_strategy_record(store, journey.RUN_ID, ref)
    assert set(record) - {"schema", "kind"} == set(STRATEGY_FIELDS)
    assert record["kind"] == "strategy"
    for field in STRATEGY_FIELDS:
        if field not in ("contract", "roster"):
            assert record[field] is not None, field
    assert record["roster"] is None, "the sample registers no roster, and the record says so"
    assert record["period"]["occurrences"] > 0
    # The pre-139 run record's field set is still what `show` projects for a record.json run.
    assert "declared_digest" in RECORD_FIELDS


def test_a_second_run_of_the_same_strategy_refuses_without_replace(tmp_path: Path) -> None:
    """One producer, one artifact: a repeated run is a retry far more often than an overwrite."""
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "store"
    frozen = _frozen(project)
    execute_run(project, frozen, store_root=store)

    with pytest.raises(RunRecordExists):
        execute_run(project, frozen, store_root=store)
    execute_run(project, frozen, store_root=store, replace_record=True)
    assert len(strategy_refs(store, journey.RUN_ID)) == 1


def test_the_registered_run_is_what_the_sample_executes(tmp_path: Path) -> None:
    """`install` registers the run it will execute, so `vqapr run sample-run` is one command."""
    project = tmp_path / "project"
    project.mkdir()
    panel = journey.install(project)

    registered = Workspace.open(project).run_definition(journey.RUN_ID)

    assert registered == journey.definition(panel)
    assert [entry.component_id for entry in registered.strategies] == [journey.STRATEGY_ID]
