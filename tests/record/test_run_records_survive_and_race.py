"""Adversarial attack on claim 4: run records survive their process, and races are refused.

Four attacks, each stronger than what `tests/flow/test_run_records.py` already covers:

1. A run INTERRUPTED mid-write -- a real OS signal to a separate process, not a hand-written
   partial record -- leaves every row it recorded and no `record.json`, and `run_ids` must not
   list it. Since `docs/issues/archive/087` the rows live in memory until the run ends, and an interrupt
   IS an end: the writer's `release` runs on the failure path and writes them.
2. A run hard-KILLED mid-write (`terminate()`, which no code can answer) keeps what the spill
   valve had already forced to disk and loses the rest -- the promise as `087` narrowed it,
   stated here so nobody reads it as the old one.
3. Five processes racing to write the SAME run id concurrently -- the collision must be refused
   (one writer wins, four raise `FileExistsError`), never interleaved into a record that belongs
   to neither.
4. A `record.json` deliberately corrupted after a successful `finish()` -- truncated to invalid
   JSON, and separately, valid JSON that is not a mapping -- and `read_record` must fail loudly
   rather than return a half-answer or silently coerce.

`multiprocessing.spawn` needs picklable top-level functions on Windows, so the interrupted,
killed and racing attacks each drive a standalone script via `subprocess.Popen` instead of
`multiprocessing.Process` with a lambda or closure.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from vqapr.record import (
    COMPACT_FILENAME,
    PART_SUFFIX,
    RECORD_FILENAME,
    RunRecordWriter,
    read_record,
    read_table,
    run_ids,
)

pytestmark = pytest.mark.concurrency

_WRITE_SCRIPT = """
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, {src!r})
from vqapr.record import RunRecordWriter


def interrupted(*_):
    raise KeyboardInterrupt


def main() -> None:
    root, run_id, spill = sys.argv[1], sys.argv[2], int(sys.argv[3])
    ten_rows = Path(sys.argv[4])
    # What the console does on Ctrl+C, wired to the one signal a test can send to a single
    # process: CTRL_BREAK on Windows (delivered as SIGBREAK), SIGTERM elsewhere.
    signal.signal(getattr(signal, "SIGBREAK", signal.SIGTERM), interrupted)
    writer = RunRecordWriter(Path(root), run_id, spill_bytes=spill)
    writer.open()
    try:
        for i in range(2000):
            writer.append("vqapr.account", [{{"instrument": "_ACCOUNT", "nav": str(1000 + i)}}])
            if i == 9:
                # The test's evidence that ten rows are in memory: `append` returned ten times.
                ten_rows.touch()
            time.sleep(0.02)
        writer.finish({{"account": {{"version": 2000}}}})
    except BaseException:
        # What `flow/orchestration.py` does on a strategy's failure path.
        writer.release()
        raise


if __name__ == "__main__":
    main()
"""

_NO_SPILL = 1 << 40

_RACE_SCRIPT = """
import sys
from pathlib import Path

sys.path.insert(0, {src!r})
from vqapr.record import RunRecordWriter


def main() -> None:
    root, run_id, index = sys.argv[1], sys.argv[2], int(sys.argv[3])
    writer = RunRecordWriter(Path(root), run_id)
    try:
        writer.open()
    except FileExistsError:
        print("REFUSED")
        return
    writer.append("vqapr.account", [{{"instrument": "_ACCOUNT", "nav": str(index)}}])
    writer.finish({{"account": {{"version": index}}}})
    print("SUCCEEDED")


if __name__ == "__main__":
    main()
"""


@pytest.fixture
def _src_root() -> str:
    return str(Path(__file__).resolve().parents[2] / "src")


def _write_script(tmp_path: Path, name: str, template: str, src_root: str) -> Path:
    script = tmp_path / name
    script.write_text(template.format(src=src_root), encoding="utf-8")
    return script


def _start_writer(
    tmp_path: Path, src_root: str, store: Path, run_id: str, spill: int, ten_rows: Path
):
    script = _write_script(tmp_path, "write_probe.py", _WRITE_SCRIPT, src_root)
    # Its own process group, so CTRL_BREAK reaches it and nothing else (Windows).
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(
        [sys.executable, str(script), str(store), run_id, str(spill), str(ten_rows)],
        creationflags=flags,
    )


def _wait_for(proc: subprocess.Popen, evidence: Callable[[], bool], what: str) -> None:
    """Until the child leaves `what` on disk: evidence, never a clock.

    This replaced "wait for the lock, then sleep one second". A cold interpreter's first parquet
    write -- pyarrow and the zstd codec loading on a fresh `.venv`, or a machine busy with the
    rest of the suite -- was measured to take longer than that second, and a signal that lands
    before the evidence exists tests a different scenario than the one the test names: a hard
    kill before the handler is installed, or a kill before the first spill part. Ten rows at
    20 ms each are a quarter of a second, so the budget below is never approached; it exists so
    a child that hangs fails by name instead of by the harness.
    """
    deadline = time.monotonic() + 120
    while not evidence():
        assert proc.poll() is None, f"the child ended before {what}"
        assert time.monotonic() < deadline, f"the child never produced {what}"
        time.sleep(0.05)


def _interrupt(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        proc.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        proc.send_signal(signal.SIGTERM)


def test_a_process_interrupted_mid_write_leaves_every_row_and_no_record(
    tmp_path: Path, _src_root: str
) -> None:
    """A real signal to a separate OS process, not a hand-authored partial record.

    `tests/flow/test_run_records.py::test_an_unfinished_run_is_not_listed_as_a_finished_one`
    calls `release()` itself in the same process. This drives a genuinely separate process and
    interrupts it externally: the rows were in memory when the signal arrived (`087`), the
    failure path's `release` wrote them, and the record was never written.
    """
    store = tmp_path / "store"
    store.mkdir()
    ten_rows = tmp_path / "ten-rows"
    proc = _start_writer(tmp_path, _src_root, store, "interrupted-run", _NO_SPILL, ten_rows)
    # Nothing reaches the disk before the end (`087`), so the child says when the tenth row is in
    # memory. Its handler was installed before `open()`, so a signal now is an interrupt and not
    # the hard kill of the test below.
    _wait_for(proc, ten_rows.exists, "its tenth row")
    _interrupt(proc)
    proc.wait(timeout=180)

    assert proc.returncode != 0, "the interrupt ended the run"
    assert run_ids(store) == (), "an interrupted run must not be listed as finished"
    assert not (store / "runs" / "interrupted-run" / RECORD_FILENAME).exists()
    table = store / "runs" / "interrupted-run" / "tables" / "vqapr.account"
    assert [path.name for path in table.iterdir()] == [COMPACT_FILENAME]
    rows = list(read_table(store, "interrupted-run", "vqapr.account"))
    assert len(rows) >= 10, "everything recorded before the signal is on disk"
    assert [row["nav"] for row in rows] == [str(1000 + i) for i in range(len(rows))]


def test_a_process_hard_killed_mid_write_keeps_only_what_had_spilled(
    tmp_path: Path, _src_root: str
) -> None:
    """`terminate()` runs no code in the victim. What the spill valve had already written
    survives; what was buffered after it is gone; no record, no compact file."""
    store = tmp_path / "store"
    store.mkdir()
    table = store / "runs" / "killed-run" / "tables" / "vqapr.account"
    proc = _start_writer(tmp_path, _src_root, store, "killed-run", 1, tmp_path / "ten-rows")
    # A part is staged under a dotted name and renamed into place, so the first `000000.parquet`
    # is a complete file: the kill lands with at least one spill part on disk, by evidence.
    _wait_for(proc, lambda: any(table.glob(f"[0-9]*{PART_SUFFIX}")), "its first spill part")
    proc.terminate()
    proc.wait(timeout=180)

    assert run_ids(store) == ()
    assert not (store / "runs" / "killed-run" / RECORD_FILENAME).exists()
    names = sorted(path.name for path in table.iterdir())
    assert names and COMPACT_FILENAME not in names, "spill parts only: the run never ended"
    rows = list(read_table(store, "killed-run", "vqapr.account"))
    assert [row["nav"] for row in rows] == [str(1000 + i) for i in range(len(rows))]


def test_five_processes_racing_the_same_run_id_refuse_rather_than_interleave(
    tmp_path: Path, _src_root: str
) -> None:
    """Five independent OS processes contend for one run id. Exactly one may win.

    `tests/flow/test_run_records.py` only ever exercises DISTINCT run ids in parallel (AC-R4) or
    a same-process double-`open()` (which proves the check exists, not that it holds under real
    contention). This launches five real processes at the same shared id and checks that the
    result is a clean single winner, never a record whose fields came from more than one writer.
    """
    store = tmp_path / "store"
    store.mkdir()
    script = _write_script(tmp_path, "race_probe.py", _RACE_SCRIPT, _src_root)

    processes = [
        subprocess.Popen(
            [sys.executable, str(script), str(store), "shared-id", str(index)],
            stdout=subprocess.PIPE,
            # stderr too, so a crashing child reports its own cause. Without it the assertion
            # below can only say a writer crashed, and the traceback that would explain WHY is
            # discarded -- which is how this failure stayed unexplained across several runs.
            stderr=subprocess.STDOUT,
            text=True,
        )
        for index in range(5)
    ]
    # 180s, matching the sibling race test below, not because a race takes that long -- it takes
    # milliseconds -- but because five Python interpreters STARTING can exceed a tight budget when
    # the full suite is already loading the machine. Measured: this passed 10/10 in isolation and
    # failed once inside a full run at 30s, which is a harness timeout wearing a product defect's
    # error message.
    outputs = [proc.communicate(timeout=180)[0].strip() for proc in processes]
    for proc, output in zip(processes, outputs, strict=True):
        assert proc.returncode == 0, (
            f"a racing writer crashed instead of refusing cleanly:\n{output}"
        )

    # KNOWN FLAKE, measured rather than assumed: roughly 1 run in 12 sees TWO winners, because a
    # peer can observe the directory after another process created it but before that process
    # wrote its lock, conclude the id is abandoned, and take it too.
    #
    # It is asserted rather than tolerated because the property is real and the failure is the
    # signal. Two attempts to close the window -- replacing the stale lock atomically, then
    # reordering so the lock precedes the directory -- each made it MORE frequent (9/12 and 12/12
    # failures) and were reverted. `src/vqapr/record/writer.py` documents the window at the
    # recovery branch. Closing it properly needs a single atomic create-and-claim, which this
    # filesystem does not offer directly.
    succeeded = [line for line in outputs if line == "SUCCEEDED"]
    refused = [line for line in outputs if line == "REFUSED"]
    assert len(succeeded) == 1, f"expected exactly one winner, got {outputs}"
    assert len(refused) == 4, f"expected four refusals, got {outputs}"

    assert run_ids(store) == ("shared-id",)
    record = read_record(store, "shared-id")
    # The record's own version must be a single consistent integer 0-4, not some corrupted mix.
    assert record["account"]["version"] in range(5)


def test_a_truncated_record_json_fails_loudly_rather_than_partially(tmp_path: Path) -> None:
    """A `record.json` truncated after a successful write -- e.g. disk full, or a copy that was
    itself interrupted -- must not be silently read as a partial or default record.
    """
    writer = RunRecordWriter(tmp_path, "truncated-run")
    writer.open()
    writer.append("vqapr.account", [{"instrument": "_ACCOUNT", "nav": "1000"}])
    writer.finish({"account": {"version": 1}})

    record_path = tmp_path / "runs" / "truncated-run" / RECORD_FILENAME
    whole = record_path.read_text(encoding="utf-8")
    record_path.write_text(whole[: len(whole) // 2], encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        read_record(tmp_path, "truncated-run")


def test_valid_json_that_is_not_a_mapping_is_not_silently_treated_as_a_record(
    tmp_path: Path,
) -> None:
    """A `record.json` that parses as JSON but is not the expected shape -- a list, say.

    `read_record` is `json.loads(path.read_text(...))` with no shape validation at all: this pins
    exactly what happens (a list is returned as-is, not refused), so a caller relying on
    `record["account"]` gets a `TypeError` two frames away from the actual defect rather than a
    refusal naming the corrupted file. Not asserted as BROKEN outright -- `read_record`'s own
    docstring only promises "one run's frozen facts, exactly as they were written" and never
    promises shape validation -- but the absence of a check here is exactly the kind of thing a
    QA lane should make visible rather than assume.
    """
    writer = RunRecordWriter(tmp_path, "shape-run")
    writer.open()
    writer.finish({"account": {"version": 1}})

    record_path = tmp_path / "runs" / "shape-run" / RECORD_FILENAME
    record_path.write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")

    # The pin above said adding a check would be an improvement and to update this when it landed.
    # Record `115` added it: the reader-side schema check cannot read a payload with no keys, so
    # the shape is verified first and refused by name.
    with pytest.raises(ValueError, match="not a mapping") as refused:
        read_record(tmp_path, "shape-run")

    message = str(refused.value)
    assert str(record_path) in message, "the refusal must name the corrupted file"
    assert "list" in message, "and what it found instead, so the reader knows what to look at"


def test_concurrent_force_runs_never_blend_two_runs_into_one_record(tmp_path: Path) -> None:
    """`--force` may be won several times; it must never produce a record that is neither run.

    Multiple winners are correct here rather than a defect: each `--force` legitimately re-claims
    an id the previous holder released, which is what forcing means. "Exactly one winner" is the
    wrong invariant to assert of it.

    The right one is that whatever survives is ONE run's. The implementation this replaced --
    remove-then-create behind the flag -- failed exactly that, and looked fine because the flag was
    assumed to be single-writer. Measured before the fix: blended records plus raw OSError and
    PermissionError escaping as `stage: "unhandled"`.
    """
    import subprocess
    import sys
    import textwrap

    from vqapr.record import read_table

    runner = tmp_path / "forcer.py"
    runner.write_text(
        textwrap.dedent(
            """
            import sys, pathlib, time
            from vqapr.record import (
                RunRecordExists,
                RunRecordLive,
                RunRecordTaken,
                RunRecordWriter,
            )
            root, run_id, nav = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
            # Converge before racing: interpreter startup is seconds, the contended window is
            # microseconds, so without a barrier these arrive one at a time and never collide.
            gate = pathlib.Path(sys.argv[4])
            while not gate.exists():
                time.sleep(0.002)
            try:
                writer = RunRecordWriter(root, run_id)
                writer.open(replace=True)
                writer.append("vqapr.account", [{"nav": nav}])
                writer.finish({"account": {"version": int(nav)}})
                print("SUCCEEDED")
            except (RunRecordExists, RunRecordLive, RunRecordTaken):
                print("REFUSED")
            except OSError as error:
                # A raw OSError here is the defect: it escapes the CLI as stage "unhandled",
                # telling an agent the framework broke when two runs simply competed for one id.
                print(f"LEAKED:{type(error).__name__}")
            """
        ),
        encoding="utf-8",
    )

    store = tmp_path / "store"
    gate = tmp_path / "GO"
    seed = RunRecordWriter(store, "shared")
    seed.open()
    seed.finish({"account": {"version": 0}})

    processes = [
        subprocess.Popen(
            [sys.executable, str(runner), str(store), "shared", str(index + 1), str(gate)],
            stdout=subprocess.PIPE,
            text=True,
        )
        for index in range(5)
    ]
    # Let every process reach the gate, then release them together. Interpreter startup is
    # seconds and the contended window is microseconds, so without this they arrive one at a
    # time and never actually race.
    time.sleep(2.0)
    gate.write_text("go", encoding="utf-8")
    outcomes = [process.communicate(timeout=180)[0].strip() for process in processes]

    # Every outcome is a decision, not a crash. This is the reliably-detectable half: the
    # implementation this replaced leaked a raw OSError or PermissionError in 19 of 20 measured
    # races, where an actual blend appeared in only 2 of 20.
    leaked = [outcome for outcome in outcomes if outcome.startswith("LEAKED:")]
    assert leaked == [], f"a racing --force crashed instead of refusing: {leaked}"

    rows = [row["nav"] for row in read_table(store, "shared", "vqapr.account")]
    version = read_record(store, "shared")["account"]["version"]
    assert len(rows) == 1, f"the record holds rows from more than one run: {rows}"
    assert rows[0] == str(version), (
        f"the record's rows ({rows}) and its own account version ({version}) came from different "
        "runs, so this is a blend rather than one run's record"
    )
