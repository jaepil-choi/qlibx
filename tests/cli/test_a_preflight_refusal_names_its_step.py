"""A preflight refusal names the step that failed and carries what raised it -- from BOTH verbs.

`docs/issues/archive/076`. Preflight round-trips a strategy's payload on fresh instances before the first
callback, and two things about that were invisible to the author who tripped it:

- **One `try` around three steps.** `save_payload` on a fresh instance, `load_payload` on a
  second, `save_payload` again -- all wrapped in one `except` that could only say "the initial
  payload cannot be staged". The author could not tell which of their two methods to open. Worse,
  `_from_python` rendered `f"{type(e).__name__}: {e}"` and dropped `__cause__`, so the `EOFError:
  Ran out of input` that was the actual reason never reached the reader at all.
- **Two doors.** `check` caught the `ValueError` and rendered a bounded refusal;
  `cli/run.py::run` called `freeze` OUTSIDE its `try`, so the same judgment left the same
  package as `stage: "unhandled"` -- which tells an agent the framework broke when the truth is
  the strategy was wrong.

The fixture is the shape a real author writes: a `load_payload` that calls `pickle.load` without
guarding an empty source. The default `save_payload` writes no bytes, so preflight hands it an
empty stream and it raises `EOFError` -- before a single callback, which is the whole point of
proving the pair in preflight.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_commands import _cli, _workspace_for_run

from vqapr.cli.check import check

_LOADS_AN_EMPTY_SOURCE = """
    def load_payload(self, source):
        import pickle

        self.restored = pickle.load(source)   # unguarded: an empty source raises EOFError
"""

_SAVES_DIFFERENT_BYTES_EACH_TIME = """
    def save_payload(self, target):
        target.write(repr(id(self)).encode("utf-8"))   # not deterministic across instances

    def load_payload(self, source):
        source.read()
"""


def _strategy_with(root: Path, methods: str) -> None:
    """Append methods to the scaffolded strategy `_workspace_for_run` already registered.

    The registration names a path, so editing the file behind it is what a user editing their own
    strategy does; nothing needs re-registering.
    """
    source = root / "my_alpha.py"
    source.write_text(source.read_text(encoding="utf-8") + methods, encoding="utf-8")


def _refusal(payload: dict) -> dict:
    failures = payload["failures"]
    assert len(failures) == 1, failures
    return failures[0]


def test_check_names_the_step_and_carries_the_cause(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The headline for `check`: which of the three steps, and what raised."""
    _workspace_for_run(tmp_path, capsys)
    _strategy_with(tmp_path, _LOADS_AN_EMPTY_SOURCE)

    body = check("r1", tmp_path)

    assert body["ok"] is False
    failure = _refusal(body)
    assert failure["code"] == "preflight.refused"
    observed = failure["observed"]
    assert "load_payload of those bytes on a second fresh instance" in observed, observed
    assert "EOFError" in observed, observed
    assert "Ran out of input" in observed, observed
    assert " <- " in observed, "the cause chain was dropped, which is the defect 076 reported"


def test_run_refuses_in_checks_stage_and_code_not_unhandled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The headline for `run`. `stage: "unhandled"` here is the bug, not the report."""
    _workspace_for_run(tmp_path, capsys)
    _strategy_with(tmp_path, _LOADS_AN_EMPTY_SOURCE)

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "run", "r1")

    assert code == 1
    assert payload["ok"] is False
    assert payload["stage"] == "freeze", (
        f"run rendered a preflight refusal as {payload['stage']!r}; `unhandled` is issue 076"
    )
    failure = _refusal(payload)
    assert failure["code"] == "preflight.refused"
    assert "EOFError" in failure["observed"], failure["observed"]


def test_both_verbs_render_the_one_refusal_identically(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One renderer, so a reader who handled `check`'s body handles `run`'s unchanged.

    Every field is compared, not just the code: a second renderer drifts in `fix` and `source`
    long before it drifts in the code, and that drift is what makes an agent write two handlers.
    """
    _workspace_for_run(tmp_path, capsys)
    _strategy_with(tmp_path, _LOADS_AN_EMPTY_SOURCE)

    checked = _refusal(check("r1", tmp_path))
    _, ran = _cli(capsys, "--project-root", str(tmp_path), "run", "r1")
    executed = _refusal(ran)

    for field in ("code", "status", "requirement", "observed", "fix"):
        assert checked[field] == executed[field], field
    assert checked["source"]["key_path"] == executed["source"]["key_path"] == "runs.r1"
    # The cause is the same exception both times; only the frames above it differ by verb.
    assert checked["cause"]["type"] == executed["cause"]["type"]
    assert checked["cause"]["where"] == executed["cause"]["where"]


def test_the_refusal_carries_every_field_and_its_cause(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`SKILL.md` guarantees the fields on every refusal; a preflight refusal is not an exception.

    The exception rides whole (record `171`): a bare `ValueError` from a framework invariant is
    classified by whose frame raised it, and the traceback is what lets the reader check that.
    """
    _workspace_for_run(tmp_path, capsys)
    _strategy_with(tmp_path, _LOADS_AN_EMPTY_SOURCE)

    failure = _refusal(check("r1", tmp_path))

    for field in ("code", "status", "requirement", "observed", "fix", "cause"):
        assert failure[field], f"{field!r} is missing or empty"
    assert failure["source"]["key_path"] == "runs.r1"
    assert failure["status"] in (500, 502)
    assert failure["cause"]["type"] == "ValueError"
    assert failure["cause"]["traceback"] and "EOFError" in failure["cause"]["traceback"], (
        "the whole chain rides in `cause.traceback`, not a cut of it"
    )
    assert failure["cause"]["where"]


def test_a_nondeterministic_save_is_named_as_the_third_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The round-trip mismatch is its own sentence, not the same one as a raising method.

    Nothing raised here -- both methods ran -- so there is no cause to chain, and the refusal has
    to say by itself that the second `save_payload` disagreed with the first.
    """
    _workspace_for_run(tmp_path, capsys)
    _strategy_with(tmp_path, _SAVES_DIFFERENT_BYTES_EACH_TIME)

    failure = _refusal(check("r1", tmp_path))

    assert failure["code"] == "preflight.refused"
    assert "save_payload again wrote different bytes" in failure["observed"], failure["observed"]
