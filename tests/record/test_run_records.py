"""Run records survive the process that wrote them, and five writers do not lose each other.

`recorder_rows` is in-memory only, which makes two things impossible rather than merely awkward:
five parallel runs cannot each be read afterwards, and a finished run cannot be asked anything
without being run again. Freezing the record to disk is the prerequisite for both, so the tests
that matter here are the ones a single-process implementation would pass by accident:

- five INDEPENDENT processes writing at once, each leaving an intact record;
- a COLD process, which never saw any of them, reading all five.

`multiprocessing.spawn` rather than `fork`: this workstation is Windows, where `fork` does not
exist, and the plan's original bash `&` does not transfer either.
"""

from __future__ import annotations

import inspect
import multiprocessing as mp
import os
import time as _time
from pathlib import Path

import pytest

from vqapr.record import (
    LOCK_FILENAME,
    LOCK_STALE_AFTER,
    RECORD_FILENAME,
    RunRecordExists,
    RunRecordLive,
    RunRecordWriter,
    read_record,
    read_table,
    run_ids,
    table_ids,
)


def _write(root: str, run_id: str, rows: int) -> None:
    """One run's whole record, written by one process that shares nothing with the others."""
    writer = RunRecordWriter(Path(root), run_id)
    writer.open()
    for index in range(rows):
        writer.append(
            "vqapr.account",
            [{"instrument": "_ACCOUNT", "nav": f"{1000 + index}", "event_time": f"t{index}"}],
        )
    writer.finish(
        {
            "account": {"version": rows, "cash": "1000", "positions": {}},
            "tables": {"vqapr.account": {"rows": rows, "instants": rows}},
            "contract": {"accepted_intents": rows},
            "source_digest": f"digest-{run_id}",
            "period": {"start": "2024-01-01", "end": "2024-12-31", "occurrences": rows},
        }
    )


def _read_all(root: str) -> dict[str, int]:
    """Read every record from a process that did no writing."""
    path = Path(root)
    return {run_id: read_record(path, run_id)["account"]["version"] for run_id in run_ids(path)}


def _spawn(tmp_path: Path, prefix: str, count: int) -> list[int]:
    context = mp.get_context("spawn")
    processes = [
        context.Process(target=_write, args=(str(tmp_path), f"{prefix}-{index}", index + 1))
        for index in range(count)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=180)
    return [process.exitcode for process in processes]


def test_a_record_outlives_the_process_that_wrote_it(tmp_path: Path) -> None:
    """The whole premise: written in a child process, read in this one.

    A same-process test would pass on an implementation that never wrote anything at all.
    """
    context = mp.get_context("spawn")
    process = context.Process(target=_write, args=(str(tmp_path), "solo", 3))
    process.start()
    process.join(timeout=120)

    assert process.exitcode == 0, "the writing process failed"
    assert run_ids(tmp_path) == ("solo",)
    record = read_record(tmp_path, "solo")
    assert record["account"]["version"] == 3
    assert next(iter(read_table(tmp_path, "solo", "vqapr.account")))["nav"] == "1000"


@pytest.mark.concurrency
def test_five_concurrent_runs_each_leave_an_intact_record(tmp_path: Path) -> None:
    """AC-R4. Five independent processes, five records, none overwriting another.

    This is the test an index file would fail. Two processes reading an index, each appending
    their own entry, and the second write erasing the first is the documented lost-update the
    workspace lock exists for -- and it fails SILENTLY, which is why this asserts all five rather
    than "at least one".
    """
    assert _spawn(tmp_path, "factor", 5) == [0] * 5
    assert run_ids(tmp_path) == tuple(f"factor-{index}" for index in range(5))

    for index in range(5):
        record = read_record(tmp_path, f"factor-{index}")
        assert record["account"]["version"] == index + 1, (
            f"factor-{index} does not hold its own values, so a writer overwrote another"
        )
        assert record["source_digest"] == f"digest-factor-{index}"
        assert len(list(read_table(tmp_path, f"factor-{index}", "vqapr.account"))) == index + 1


@pytest.mark.concurrency
def test_a_cold_process_reads_every_record_it_never_saw_written(tmp_path: Path) -> None:
    """AC-R5. The reader shares no memory with any writer, which is the only honest test of this.

    A reader inside the writing process could be answering from state that happened to survive
    rather than from anything on disk.
    """
    assert _spawn(tmp_path, "run", 5) == [0] * 5

    with mp.get_context("spawn").Pool(1) as pool:
        seen = pool.apply(_read_all, (str(tmp_path),))

    assert seen == {f"run-{index}": index + 1 for index in range(5)}


def test_an_unfinished_run_is_not_listed_as_a_finished_one(tmp_path: Path) -> None:
    """A run that ended without its record leaves rows and no record. Listing it would claim
    facts nobody wrote."""
    writer = RunRecordWriter(tmp_path, "killed")
    writer.open()
    writer.append("vqapr.account", [{"instrument": "_ACCOUNT", "nav": "1000"}])
    # What the failure path does (`087`): the rows land, the record never does.
    writer.release()

    assert run_ids(tmp_path) == ()
    assert not (tmp_path / "runs" / "killed" / RECORD_FILENAME).exists()
    assert list(read_table(tmp_path, "killed", "vqapr.account"))


def test_a_second_run_under_one_id_is_refused_rather_than_interleaved(tmp_path: Path) -> None:
    """Two runs sharing an id would produce a record that is neither of them.

    `RunRecordExists` specifically, not a bare `FileExistsError`: the type is the point. A bare one
    escapes the CLI as `stage: "unhandled"`, which tells an agent the framework broke when the
    truth is that a run id was chosen twice. Asserting the base class would pass on the untyped
    version this replaced.
    """
    # A COMPLETED run: the refusal is about a finished record, not a directory. A run that never
    # reached `finish` left nothing any reader would return, and retrying it is covered above.
    first = RunRecordWriter(tmp_path, "once")
    first.open()
    first.finish({"account": {"version": 1}})

    with pytest.raises(RunRecordExists) as refused:
        RunRecordWriter(tmp_path, "once").open()

    assert refused.value.run_id == "once"
    assert refused.value.directory == tmp_path / "runs" / "once"


def test_replacing_a_record_removes_it_rather_than_merging_into_it(tmp_path: Path) -> None:
    """`--force`'s actual behaviour, which nothing exercised until it was already live.

    Merging is the failure this avoids: a second run appending into the first run's directory
    produces a record that is neither run, and every table would carry rows from both. So the old
    directory goes entirely, and what remains is exactly one run's record.
    """
    first = RunRecordWriter(tmp_path, "again")
    first.open()
    first.append("vqapr.account", [{"nav": "1000", "event_time": "t0"}])
    first.append("stale.table", [{"gone": "yes"}])
    first.finish({"account": {"version": 1}})

    second = RunRecordWriter(tmp_path, "again")
    second.open(replace=True)
    second.append("vqapr.account", [{"nav": "2000", "event_time": "t1"}])
    second.finish({"account": {"version": 2}})

    assert read_record(tmp_path, "again")["account"]["version"] == 2
    rows = list(read_table(tmp_path, "again", "vqapr.account"))
    assert [row["nav"] for row in rows] == ["2000"], "the first run's rows survived the replace"
    assert table_ids(tmp_path, "again") == ("vqapr.account",), (
        "a table only the replaced run recorded is still present, so this merged rather than "
        "replaced"
    )


def test_a_dead_run_s_id_is_reclaimed_by_an_ordinary_retry(tmp_path: Path) -> None:
    """A crashed run costs the operator nothing: no flag, no manual cleanup.

    An earlier design refused any leftover directory and charged `--force` to clear it. That was a
    real cost for someone else's crash, and it existed only because the claim was the DIRECTORY --
    which cannot distinguish a dead run from a live one.

    The claim is now liveness. A dead holder's lock is stale, so a plain retry reclaims the id;
    the flag is reserved for replacing a run that genuinely finished.
    """
    crashed = RunRecordWriter(tmp_path, "interrupted")
    crashed.open()
    crashed.append("vqapr.account", [{"nav": "1000"}])
    assert run_ids(tmp_path) == (), (
        "the fixture must leave an unfinished run, or this proves nothing"
    )

    # The holder died: its lock stops being refreshed and ages out.
    lock = crashed.directory / LOCK_FILENAME
    dead = _time.time() - (LOCK_STALE_AFTER * 10)
    os.utime(lock, (dead, dead))

    retry = RunRecordWriter(tmp_path, "interrupted")
    retry.open()
    retry.append("vqapr.account", [{"nav": "2000"}])
    retry.finish({"account": {"version": 1}})

    assert run_ids(tmp_path) == ("interrupted",)
    rows = list(read_table(tmp_path, "interrupted", "vqapr.account"))
    assert [row["nav"] for row in rows] == ["2000"], (
        "the crashed run's rows survived into the retry, so this merged rather than restarted"
    )


def test_a_slow_run_keeps_its_id_because_it_refreshes_its_own_lock(tmp_path: Path) -> None:
    """`LOCK_STALE_AFTER` is a heartbeat threshold, not a run-duration budget.

    Read as a duration budget it recreates the exact defect the lock exists to prevent. A factor
    run over this testbed takes three to six minutes -- well past the window -- so without a
    refresh every real run would age out mid-flight and any peer could take its id. Measured
    against an unrefreshed lock: a live run and a thief wrote into one directory and the surviving
    record held `['B1', 'A2']`, which is neither run.

    The run touches its lock as it works, so only a run that has STOPPED touching it reads as dead.
    """
    live = RunRecordWriter(tmp_path, "slow")
    live.open()
    live.append("vqapr.account", [{"nav": "A1"}])

    # Age the lock past the window, as a long run would.
    lock = live.directory / LOCK_FILENAME
    stale = _time.time() - (LOCK_STALE_AFTER + 60)
    os.utime(lock, (stale, stale))

    # The run is still working, and that is what keeps the claim alive.
    live.append("vqapr.account", [{"nav": "A2"}])

    with pytest.raises(RunRecordLive):
        RunRecordWriter(tmp_path, "slow").open()

    live.finish({"account": {"version": 1}})
    assert [row["nav"] for row in read_table(tmp_path, "slow", "vqapr.account")] == ["A1", "A2"]


def test_a_live_run_is_never_replaced_even_with_force(tmp_path: Path) -> None:
    """The failure this whole mechanism exists for, and it needs no race to reproduce.

    Two terminals: run A holds an id and is appending; the operator forces the same id. With the
    directory as the claim, B removed A's directory and created its own, A's next append
    re-resolved the path -- `append` opens and closes per chunk and holds nothing -- and wrote into
    B's. Both finished into one record, and `run_ids` listed one complete run whose tables held two
    runs' rows. Measured: `['B1', 'A2']`.
    """
    live = RunRecordWriter(tmp_path, "busy")
    live.open()
    live.append("vqapr.account", [{"nav": "A1"}])

    with pytest.raises(RunRecordLive) as refused:
        RunRecordWriter(tmp_path, "busy").open(replace=True)
    assert refused.value.claim.pid == os.getpid()
    assert "rm strategy" in str(refused.value), "the refusal must name a remedy that is not --force"

    # A keeps writing and finishes intact.
    live.append("vqapr.account", [{"nav": "A2"}])
    live.finish({"account": {"version": 1}})
    assert [row["nav"] for row in read_table(tmp_path, "busy", "vqapr.account")] == ["A1", "A2"]


def test_replace_is_off_by_default_so_a_retry_cannot_clobber(tmp_path: Path) -> None:
    """The direction of the default is the whole decision.

    In a five-process factor loop a repeated run to the same id is far more often a retry than an
    intended overwrite. A refusal costs one flag; an accidental clobber is unrecoverable.
    """
    writer = RunRecordWriter(tmp_path, "precious")
    writer.open()
    writer.append("vqapr.account", [{"nav": "1000"}])
    writer.finish({"account": {"version": 7}})

    with pytest.raises(RunRecordExists):
        RunRecordWriter(tmp_path, "precious").open()

    assert read_record(tmp_path, "precious")["account"]["version"] == 7


def test_the_run_loop_signals_progress_once_per_occurrence(tmp_path: Path) -> None:
    """The heartbeat's wiring, pinned deterministically rather than by a timing test.

    The end-to-end proof lives in `test_run_freezes_its_record.py` and drives `public.run`, which
    is what makes it trustworthy -- but it depends on a real run outlasting a sleep, and it is
    currently the only thing standing between the product and a silent regression of a defect that
    let a peer delete a live run's tables. This pins the same wiring in milliseconds: the callback
    fires once per occurrence, so a run that records no rows still proves it is alive.
    """
    from vqapr.flow.engine.loop import EventLoop
    from vqapr.flow.strategy.loop import StrategyEventLoop

    signature = inspect.signature(StrategyEventLoop.__init__)
    assert "on_progress" in signature.parameters, (
        "the run loop no longer accepts a progress signal, so a long run cannot prove it is alive"
    )

    # The walk is the shared loop both kinds of run use (record `148`).
    source = inspect.getsource(EventLoop.run)
    loop = source.index("while next_static is not None")
    branch = source.index("due = self.pending()", loop)
    assert "self._on_progress()" in source[loop:branch], (
        "the progress signal must fire at the top of the occurrence loop, before the due/static "
        "branch, or a run made entirely of due executions never signals"
    )


def test_an_unwritable_store_is_not_reported_as_a_taken_run_id(tmp_path: Path) -> None:
    """A confident wrong diagnosis is worse than an honest unhandled error.

    `open` converts contention into a refusal, and an unscoped version of that boundary turned a
    full disk, a read-only mount and a bad path into "this id is taken" -- whose advertised
    remedies, another id or `--force`, cannot fix any of them. An agent would cycle through ids,
    escalate to a destructive flag, and never learn the store is unwritable.

    Contention presupposes somebody else created the directory; if it is not there, nobody is
    competing.
    """
    blocked = tmp_path / "store-is-a-file"
    blocked.write_text("not a directory", encoding="utf-8")

    with pytest.raises(OSError) as failed:
        RunRecordWriter(blocked, "x").open()

    assert not isinstance(failed.value, RunRecordExists), (
        "an environment failure was reported as a taken run id, so the remedy named cannot work"
    )


def test_tables_are_discovered_rather_than_declared(tmp_path: Path) -> None:
    """What a run recorded is a fact about the run, read back from what it wrote."""
    writer = RunRecordWriter(tmp_path, "multi")
    writer.open()
    writer.append("vqapr.account", [{"nav": "1"}])
    writer.append("factor.membership", [{"instrument": "A"}])
    writer.finish({})

    assert table_ids(tmp_path, "multi") == ("factor.membership", "vqapr.account")
