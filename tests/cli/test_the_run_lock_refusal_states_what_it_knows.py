"""A held run id is reported as a lock with an age, not as a process that is running.

`docs/issues/037`. A run was killed by a two-minute tool timeout, 216 of ~246 callbacks in. The
identical command, re-run seconds later, was refused with `'run_ou_k0_2024' is running now at
.vqapr/runs/run_ou_k0_2024 (pid 64004)` -- and `Get-Process -Id 64004` returned nothing.

**The mechanism was right and the message was wrong.** `LOCK_STALE_AFTER` is a heartbeat threshold:
a lock unrefreshed for 120 seconds is treated as abandoned, so the dead run's id frees itself. What
the refusal knew was "this lock was touched recently"; what it said was "is running now", printing a
pid nothing had interrogated. Inside that window a killed run and a live one are indistinguishable
by construction -- and that window is exactly when an operator retries after a Ctrl-C, a CI timeout
or an OOM kill.

The remedy that costs nothing -- wait ~120s, then re-run the same command -- appeared in no message
and nowhere in the skill. What appeared instead was "wait for that run to finish", which for a dead
holder reads as wait forever, and a bolded argument against `--force`, the one thing that does work
on a dead claim, resting on a premise the refusal cannot check.

Since record 139 the lock guards a strategy RECORD under a registered run rather than a run id
chosen on the command line, so `--run-id <new-id>` is no longer a remedy anyone can type. What
remains is the wait, and `--force` hedged on the premise the refusal cannot check.
"""

from __future__ import annotations

import os
import time as _time
from pathlib import Path

import pytest

from vqapr.cli.run import _held_record
from vqapr.flow.run_records import (
    LOCK_FILENAME,
    LOCK_STALE_AFTER,
    LockClaim,
    RunRecordLive,
    RunRecordWriter,
    _lock_claim,
)


def test_a_fresh_lock_reports_its_age_and_a_stale_one_reports_nothing(tmp_path: Path) -> None:
    """The read carries the age out with the pid, because the age is what the message needs."""
    writer = RunRecordWriter(tmp_path, "live")
    writer.open()
    lock = writer.directory / LOCK_FILENAME

    claim = _lock_claim(lock)
    assert claim is not None
    assert claim.pid == os.getpid()
    assert claim.age < 5.0, "a lock just written is seconds old, not minutes"
    assert claim.releases_in == pytest.approx(LOCK_STALE_AFTER - claim.age, abs=1.0)

    dead = _time.time() - (LOCK_STALE_AFTER * 10)
    os.utime(lock, (dead, dead))
    assert _lock_claim(lock) is None, "an abandoned lock must read as free, or a crash is fatal"


def test_the_exception_states_a_lock_and_its_release_rather_than_liveness(tmp_path: Path) -> None:
    """`RunRecordLive` is raised on evidence of a claim, so it must speak of a claim."""
    first = RunRecordWriter(tmp_path, "busy")
    first.open()

    with pytest.raises(RunRecordLive) as refused:
        RunRecordWriter(tmp_path, "busy").open()

    message = str(refused.value)
    assert refused.value.holder == os.getpid(), "the pid stays available to callers"
    assert refused.value.claim.age >= 0.0
    assert "last refreshed" in message
    assert "released automatically" in message
    assert "Wait" in message and "vqapr rm strategy" in message, (
        "the refusal must name a remedy that is not --force"
    )
    assert "--force" not in message, "the exception itself must not send a reader to --force"
    assert "is already running" not in message, (
        "the lock proves it was touched recently, not that its process is alive"
    )


def test_the_refusal_names_the_wait_before_the_flags() -> None:
    """The CLI-facing message, built from a claim without executing a run.

    A dead holder's claim: 3 seconds old, so 117 seconds from releasing itself.
    """
    refusal = _held_record(
        RunRecordLive(
            "run_ou_k0_2024/ou-k0@abcdef01",
            Path(".vqapr/runs/run_ou_k0_2024/strategies/ou-k0@abcdef01"),
            LockClaim(64004, 3.0),
        ),
    )
    # Read through the envelope the agent actually parses, so a field renamed on the way out
    # fails here rather than in a journey.
    failure = refusal.as_dict()["failures"][0]

    assert "3s ago" in failure["observed"], "the age is the fact that separates dead from live"
    assert "not interrogated" in failure["observed"], (
        "the pid is copied out of the lock file; claiming otherwise is what the reader checked"
    )
    assert "is running now" not in failure["observed"]

    assert failure["fix"].startswith("wait about 117s"), (
        "the zero-cost remedy comes first; 'wait for that run to finish' reads as wait forever "
        "when the holder is dead"
    )
    assert "reclaims the record" in failure["fix"], (
        "waiting must be stated as a remedy, not as patience"
    )
    assert "--run-id" not in failure["fix"], (
        "a run id is a registration, not a flag; a remedy naming one cannot be typed"
    )
    assert "while the holder may be live" in failure["fix"], (
        "--force must be hedged on the premise this refusal cannot check"
    )
    assert "Do NOT use --force" not in failure["fix"], (
        "the unconditional prohibition was wrong for the dead-holder case, which is the common one"
    )


def test_the_skill_states_the_run_lock_self_healing() -> None:
    """The concept was already written down for the workspace lock and not for this one."""
    # Whitespace-normalized, because the skill is hard-wrapped and a sentence that happens to
    # break across two lines is the same sentence.
    skill = " ".join(
        Path("src/vqapr/agent/skill/SKILL.md").read_text(encoding="utf-8").split()
    )

    assert "heartbeat window" in skill
    assert "releases itself 120 seconds after its last refresh" in skill
    assert "never interrogated" in skill
