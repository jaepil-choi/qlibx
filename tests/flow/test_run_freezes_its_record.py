"""A real run freezes a real record, and a second run under one id refuses by name.

This path shipped with no coverage at all. `public.run(store_root=...)` was never called from any
test, showcase or script, so `replace=`, `RunRecordExists`, the CLI's `--force` handler and
`_freeze_record`'s drift guard were all live and unexercised -- which is how the `--force` flag
came to be named as the remedy for a refusal it cannot resolve.

The run here is the shipped sample journey, because a record is only worth freezing if a real run
produced it: a hand-built `SimulationResult` would exercise the writer while proving nothing about
what a run actually records.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import vqapr.agent.sample.journey as journey
from vqapr.flow.run_records import RunRecordExists, read_record, run_ids, table_ids
from vqapr.public import (
    AccountMode,
    AccountSnapshot,
    ConstraintSet,
    MonitoringPolicy,
    OperationRole,
    RunDefinition,
    Workspace,
    preflight_run,
)
from vqapr.public import run as execute_run


def _definition(root: Path) -> RunDefinition:
    panel = journey.install(root)
    sessions = journey._sessions(panel)
    return RunDefinition(
        strategy=journey._strategy(root),
        valuation=journey._valuation(),
        constraints=ConstraintSet(()),
        monitoring=MonitoringPolicy(journey.MONITORING_AGENDA, OperationRole.MONITORING),
        exchange=Workspace.open(root).component(journey.EXCHANGE_ID),
        execution_input_id=journey.EXECUTION_ID,
        start=datetime.fromisoformat(f"{sessions[0].isoformat()}T00:00:00{journey.OFFSET}"),
        end=datetime.fromisoformat(f"{sessions[-1].isoformat()}T23:59:59{journey.OFFSET}"),
        initial_account_snapshot=AccountSnapshot(
            version=0, cash=journey.OPENING_CASH, positions={}
        ),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=panel.instruments,
    )


@pytest.mark.slow
def test_a_run_freezes_a_record_a_later_process_could_read(tmp_path: Path) -> None:
    """AC-R3 end to end, from a real run rather than a constructed result."""
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "store"
    frozen = preflight_run(project, _definition(project))

    result = execute_run(project, frozen, store_root=store, run_id="frozen")

    assert run_ids(store) == ("frozen",)
    record = read_record(store, "frozen")
    # The five AC-R3 facts a later reader cannot reconstruct from the rows alone.
    assert record["account"]["version"] == result.final_state.account.snapshot.version
    assert record["tables"], "a run that recorded nothing would make the record pointless"
    assert record["source_digest"]
    assert record["period"]["occurrences"] == len(result.occurrences)
    assert "contract" in record
    assert table_ids(store, "frozen"), "the recorded tables must be on disk beside the record"


@pytest.mark.slow
def test_the_record_and_show_run_cannot_drift_apart(tmp_path: Path) -> None:
    """The record and `show run` read one field set, checked against a REAL frozen record.

    `_freeze_record` builds its payload by iterating `RECORD_FIELDS`, so a field named without a
    builder is a `KeyError` at the writer before anything reaches disk -- verified live when a
    probe added one. The set equality below therefore holds by construction and is a smoke check,
    not the guarantee; what this test is really worth is that it drives a REAL run, so it fails on
    a dropped field, an encoding bug, or a writer that never wrote at all. The per-field
    assertions are the part that can fail.
    """
    from vqapr.cli.show import RECORD_FIELDS

    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "store"
    execute_run(
        project, preflight_run(project, _definition(project)), store_root=store, run_id="paired"
    )

    frozen = read_record(store, "paired")
    # `schema` is the record's own metadata; every other key must be one `show run` surfaces.
    assert set(frozen) - {"schema"} == set(RECORD_FIELDS)

    # The assertions that can actually fail: every surfaced field carries a real value, so a
    # builder that silently returned nothing is caught rather than counted.
    for field in set(RECORD_FIELDS) - {"contract"}:
        assert frozen[field] is not None, f"{field} was surfaced empty"
    assert frozen["period"]["occurrences"] > 0
    assert frozen["tables"], "a real run recorded no tables at all"


@pytest.mark.slow
def test_a_second_run_under_one_id_refuses_and_force_replaces(tmp_path: Path) -> None:
    """The `--force` path, which was live and untested.

    Refusing by default is the decision: a repeated run to the same id is far more often a retry
    than an intended overwrite, and an accidental clobber is unrecoverable while a refusal costs
    one flag.
    """
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "store"
    definition = _definition(project)
    execute_run(project, preflight_run(project, definition), store_root=store, run_id="twice")

    with pytest.raises(RunRecordExists) as refused:
        execute_run(project, preflight_run(project, definition), store_root=store, run_id="twice")
    assert refused.value.run_id == "twice"

    # And the deliberate override works, leaving exactly one record.
    execute_run(
        project,
        preflight_run(project, definition),
        store_root=store,
        run_id="twice",
        replace_record=True,
    )
    assert run_ids(store) == ("twice",)


@pytest.mark.slow
def test_a_long_run_is_seen_as_live_while_it_is_still_executing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The liveness signal must come from the RUN, not from writing rows.

    An earlier version heartbeated inside `append`, and a test drove `append` directly and passed.
    It proved nothing: in the product path `append` runs only from `_freeze_record`, AFTER
    `flow.run()` returns, so the lock was stamped once at `open` and never touched again for the
    whole run. A factor run takes three to six minutes against a two-minute window, so every real
    run aged out mid-flight and any peer could take its id with no flag and delete its tables.

    So this drives `public.run` -- the path the product uses -- with the window shrunk, and asks a
    peer what it sees while the run is still going. Driving the writer instead is exactly the
    mistake that made the previous test vacuous.
    """
    import threading
    import time

    from vqapr.flow import run_records

    monkeypatch.setattr(run_records, "LOCK_STALE_AFTER", 0.5)
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "store"
    frozen = preflight_run(project, _definition(project))

    seen: list[str] = []

    def peer() -> None:
        # Far past the window, while the run is certainly still executing.
        time.sleep(6)
        try:
            run_records.RunRecordWriter(store, "live").open()
            seen.append("STOLEN")
        except run_records.RunRecordLive:
            seen.append("LIVE")
        except Exception as unexpected:
            seen.append(type(unexpected).__name__)

    watcher = threading.Thread(target=peer)
    watcher.start()
    execute_run(project, frozen, store_root=store, run_id="live")
    watcher.join(timeout=120)

    assert seen == ["LIVE"], (
        "a run still executing was not seen as live, so its id can be stolen and its tables "
        "deleted mid-flight"
    )


@pytest.mark.slow
def test_a_run_without_a_store_root_freezes_nothing(tmp_path: Path) -> None:
    """An in-process caller already holds the result and must not be made to write it to disk."""
    project = tmp_path / "project"
    project.mkdir()

    execute_run(project, preflight_run(project, _definition(project)))

    assert run_ids(tmp_path / "store") == ()
