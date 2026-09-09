"""A judgment that could not answer is reported as blocked, never as passed.

`docs/issues/archive/077`. `judgments()` has the right mechanism -- each judge runs inside a wrapper that
turns an exception into a BLOCKED entry, and its own comment says why: "the judgment did not find
nothing, it could not look, and a run nothing was proven about would then report as clean and
ready." Five helpers caught INSIDE that wrapper and returned an empty result, which is
indistinguishable from "asked the question, found nothing wrong". `check` therefore answered

    {"passed": ["workspace", "run", "judgments"], "blocked": []}

on a run whose look-ahead judgment -- AC-C5, the one `docs/issues/archive/015` exists for -- never ran.

Two reproductions, from unrelated causes, both of which used to produce exactly that report. The
run was still refused in both, but only because preflight happens to reach the same doors, and
nothing pinned that coupling. These tests pin the report instead: the property is that `check`
distinguishes "this passed" from "this never ran" from "this failed", which is what the verb is
for.

Owner decision, 2026-09-04: when a judgment cannot answer AND preflight refuses the same
underlying defect, the envelope carries BOTH. They are two different statements.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
from test_commands import _workspace_for_run

from vqapr.cli.check import check


def _corrupt_the_sessions_dataset(root: Path) -> None:
    """The execution table the run derives its trading days from (design §3.3) stops being
    readable after registration.

    `register` has already accepted it, and nothing re-validates a source file afterwards, so this
    is a state a real workspace reaches: the file moved, was rewritten, or was truncated between
    declaring the run and checking it.
    """
    (root / "execution.parquet").write_bytes(b"not a parquet file")


def _make_available_at_naive(root: Path) -> None:
    """The same venue rows, but `trade_at` is a naive TIMESTAMP instead of TIMESTAMPTZ."""
    table = root / "execution.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
              (TIMESTAMP '2024-03-05 15:30:00', 'A', true, 100.0),
              (TIMESTAMP '2024-03-06 15:30:00', 'A', true, 103.0),
              (TIMESTAMP '2024-03-07 15:30:00', 'A', true, 105.0)
            ) AS t(trade_at, instrument, is_tradable, close))
            TO '{table.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()


@pytest.mark.parametrize(
    ("name", "break_it"),
    [("corrupt_source", _corrupt_the_sessions_dataset), ("naive_available_at", _make_available_at_naive)],
)
def test_an_underivable_agenda_blocks_rather_than_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str, break_it: object
) -> None:
    """The headline. Both causes stop the agenda being derived; neither may read as passed."""
    _workspace_for_run(tmp_path, capsys)
    break_it(tmp_path)  # type: ignore[operator]

    body = check("r1", tmp_path)

    assert body["ok"] is False
    assert "judgments" not in body["passed"], (
        f"[{name}] check reported the judgments as PASSED while the agenda could not be derived: "
        f"{json.dumps(body)}"
    )
    assert body["blocked"], f"[{name}] nothing was recorded as blocked: {json.dumps(body)}"


def test_both_judgments_that_need_the_agenda_block_with_the_same_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One derivation, one failure, and every judge that asked for it hears the same thing.

    `_agenda_once` derives at most once (`docs/issues/archive/069`) and re-raises the stored exception to
    each asker. Blocking one dependent judgment and passing the other would be a report that
    contradicts itself.
    """
    _workspace_for_run(tmp_path, capsys)
    _corrupt_the_sessions_dataset(tmp_path)

    blocked = check("r1", tmp_path)["blocked"]
    by_check = _by_judge(blocked)

    assert "execution_ordering" in by_check, by_check
    assert "datasets[my-alpha]" in by_check, by_check
    assert by_check["execution_ordering"] == by_check["datasets[my-alpha]"], (
        f"the two judgments that share one agenda blocked for different reasons: {by_check}"
    )


def _by_judge(blocked: list[dict]) -> dict[str, str]:
    """`{judge name: reason}` from the blocked entries, which are `judgment.blocked` failures.

    A blocked judgment renders through the one failure shape (record `171`): `observed` opens
    with the judge's name, and the exception rides whole in `cause`.
    """
    out: dict[str, str] = {}
    for entry in blocked:
        assert entry["code"] == "judgment.blocked", entry
        name, reason = entry["observed"].split(" could not answer: ", 1)
        out[name] = reason
    return out


def test_a_blocked_entry_carries_its_cause_whole(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`cause` rides separately so a framework bug reads differently from a decline: its type,
    its message, the whole traceback, and a status saying whose fault it is."""
    _workspace_for_run(tmp_path, capsys)
    _corrupt_the_sessions_dataset(tmp_path)

    for entry in check("r1", tmp_path)["blocked"]:
        cause = entry["cause"]
        assert cause["type"], entry
        assert entry["observed"].split(" could not answer: ", 1)[1].startswith(
            f"{cause['type']}:"
        ), entry
        assert cause["traceback"] and cause["type"] in cause["traceback"], entry
        assert cause["where"], "every failure names the line it came from"
        assert entry["status"] >= 400


def test_the_defect_is_named_twice_and_that_is_the_decision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Owner decision, 2026-09-04: a blocked entry AND preflight's refusal both ride.

    The five `try` blocks this closes existed to suppress the first of those. Both are kept
    because they are different statements: one says the question could not be asked, the other
    says what is wrong. This test exists so that a later change removing either half fails loudly
    rather than quietly restoring the defect.
    """
    _workspace_for_run(tmp_path, capsys)
    _corrupt_the_sessions_dataset(tmp_path)

    body = check("r1", tmp_path)

    assert body["blocked"], "the question that could not be asked is not reported"
    assert body["failures"], "the defect itself is not reported"
    assert "source.distinct_unreadable" in {f["code"] for f in body["failures"]}


def test_one_member_that_does_not_load_does_not_silence_another_members_datasets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`datasets` is dispatched per member, so an unloadable component blocks only its own entry.

    Before this, the dataset judgment looped over members and `continue`d past one that would not
    load -- reporting the whole judgment as passed. Blocking the whole judgment instead would be
    the opposite error: this verb promises every INDEPENDENT problem at once, and one member
    failing to load says nothing about another member's datasets.
    """
    _workspace_for_run(tmp_path, capsys)
    source = tmp_path / "my_alpha.py"
    source.write_text(
        source.read_text(encoding="utf-8") + "\nraise RuntimeError('this module does not import')\n",
        encoding="utf-8",
    )

    body = check("r1", tmp_path)

    assert body["ok"] is False
    assert "judgments" not in body["passed"], json.dumps(body)
    datasets = [name for name in _by_judge(body["blocked"]) if name.startswith("datasets[")]
    assert datasets, f"the unloadable member was not reported as blocked: {json.dumps(body)}"
    # The NAME is where the reader learns which member: the exception's own text does not say.
    assert datasets[0] == "datasets[my-alpha]", datasets


def test_a_healthy_run_still_passes_every_judgment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other half of the property: nothing here makes a good run look blocked.

    A gate that fires on a clean workspace would be worse than the defect it replaces, so the
    fixture `check` is expected to bless is checked too.
    """
    _workspace_for_run(tmp_path, capsys)

    body = check("r1", tmp_path)

    assert body["ok"] is True, json.dumps(body)
    assert body["blocked"] == []
    assert "judgments" in body["passed"]
