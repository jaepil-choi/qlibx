"""The envelope is the agent's only parsing contract, so its shape is protected here."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from vqapr.cli.envelope import failure, success
from vqapr.domain.errors import (
    Failure,
    FailureSource,
    Stage,
    Status,
    VqaprError,
)

_FIELDS = (
    "code", "status", "source", "requirement", "observed", "fix", "cause", "examples",
    "example_total",
)


def _error() -> VqaprError:
    return VqaprError(
        stage=Stage.LOAD,
        failures=[
            Failure.bounded(
                "component.wrong_type",
                "must implement",
                status=Status.CONTRACT,
                observed="S",
                source=FailureSource(file="strategies.py", key_path="UserStrategy", line=12),
                fix="subclass StrategyModel, then register the component again",
            )
        ],
        mutation=False,
        retry_precondition="fix and register the component again, then retry",
    )


def test_success_and_failure_share_their_envelope_keys() -> None:
    """An agent must not need to know which outcome it got before parsing it."""
    ok = success("component.register", id="x")
    bad = failure(_error(), stage=Stage.REGISTER)
    assert ok["ok"] is True
    assert bad["ok"] is False
    assert {"ok", "stage"} <= set(ok)
    assert {"ok", "stage"} <= set(bad)


def test_failure_preserves_the_package_verdict_verbatim() -> None:
    """The CLI must not invent stage, code, or remedy text of its own.

    The `stage` handed to `failure()` is for an exception the package did not classify; a
    `VqaprError` already knows its own, and that one is what the envelope carries.
    """
    payload = failure(_error(), stage=Stage.REGISTER)
    assert payload["stage"] == "load"
    assert "family" not in payload
    assert payload["failures"][0]["code"] == "component.wrong_type"
    assert payload["failures"][0]["status"] == 422
    assert payload["retry_precondition"] == "fix and register the component again, then retry"


def test_every_envelope_field_survives_a_json_round_trip() -> None:
    """The envelope is the agent's only parsing contract, so it must survive serialization whole.

    A field that renders but does not round-trip is worse than a missing one: it reads correctly
    in a log and arrives as something else in the consumer. `source` is the field at risk, because
    it is the only nested structure in the payload.
    """
    payload = failure(_error(), stage=Stage.REGISTER)
    restored = json.loads(json.dumps(payload))

    assert restored == payload, "the envelope did not survive a JSON round trip unchanged"

    entry = restored["failures"][0]
    assert entry["fix"] == "subclass StrategyModel, then register the component again"
    assert entry["status"] == 422
    # `source` stays a structure. Flattening it to "strategies.py:12" would force every consumer to
    # write a regex, and that regex would break silently the day the format changed.
    assert entry["source"] == {"file": "strategies.py", "key_path": "UserStrategy", "line": 12}
    # So does `cause`: the raise site of a deliberate refusal, with no traceback to carry.
    assert entry["cause"]["where"].endswith("test_envelope.py:29 (_error)"), entry["cause"]
    assert entry["cause"]["traceback"] is None


def test_a_refusal_carries_every_envelope_field() -> None:
    """An agent parses these by name, so every one of them must be present and populated."""
    entry = failure(_error(), stage=Stage.REGISTER)["failures"][0]

    assert list(entry) == list(_FIELDS), "the one key order, from `Failure.as_dict`"
    for field in ("code", "status", "requirement", "fix", "cause"):
        assert entry[field], f"{field!r} is present but empty, which tells the reader nothing"
    assert "explain" not in entry


def test_an_absent_location_says_so_rather_than_inventing_one() -> None:
    """Not every refusal has a file or a line, and guessing one would send the reader somewhere."""
    unlocated = VqaprError(
        stage=Stage.FREEZE,
        failures=[
            Failure.bounded(
                "account.mode",
                "a long-only account must not hold a short",
                status=Status.PRECONDITION,
                observed="A005930: -10",
                fix="drop the short holding, or declare the account SIGNED",
            )
        ],
    )

    source = failure(unlocated, stage=Stage.RUN)["failures"][0]["source"]

    assert source == {"file": None, "key_path": None, "line": None}


def _raised(depth: int) -> RuntimeError:
    def deep(n: int) -> None:
        if n == 0:
            raise RuntimeError("bottom")
        deep(n - 1)

    try:
        deep(depth)
    except RuntimeError as error:
        return error
    raise AssertionError("unreachable")


def test_an_unclassified_exception_is_one_real_failure_with_its_cause_whole(
    tmp_path: Path,
) -> None:
    """Record `171`: no more `stage: "unhandled"` with an empty failure list.

    The exception nobody classified is a failure like any other -- `code: "unhandled"`, a status
    by whose frame raised it, and the WHOLE traceback in `cause` -- so an agent can tell the
    framework's bug from its own (`docs/issues/076`). The stage is the command's, because the
    exception does not know it and the command does.
    """
    error = _raised(40)

    payload = failure(error, project_root=tmp_path, stage=Stage.RUN)

    assert payload["ok"] is False
    assert payload["stage"] == "run"
    assert payload["error"] == "RuntimeError: bottom"
    (entry,) = payload["failures"]
    assert list(entry) == list(_FIELDS)
    assert entry["code"] == "unhandled"
    # Raised from this test file, which is outside the package: the user's frame is innermost.
    assert entry["status"] == 502
    assert entry["cause"]["type"] == "RuntimeError"
    assert entry["cause"]["message"] == "bottom"
    assert entry["cause"]["origin"] == "user"
    assert entry["cause"]["where"].endswith("test_envelope.py:123 (deep)"), entry["cause"]
    traceback = entry["cause"]["traceback"]
    # Whole, as Python itself prints it: the interpreter folds a recursion into
    # `[Previous line repeated N more times]`, which is its formatting and not a cut of ours.
    assert traceback.startswith("Traceback (most recent call last):")
    assert "[Previous line repeated 37 more times]" in traceback, traceback
    assert traceback.rstrip().endswith("RuntimeError: bottom")
    assert "traceback" not in payload, "nothing rides outside the failure entry"
    assert entry["fix"], "even an unhandled failure names the next action"


def test_a_short_traceback_is_also_written_beside_the_workspace(tmp_path: Path) -> None:
    """The diagnostics file is an extra for a reader with a terminal, never a substitute."""
    payload = failure(_raised(1), project_root=tmp_path, stage=Stage.RUN)

    written = Path(payload["detail"])
    assert written.exists()
    assert "RuntimeError" in written.read_text(encoding="utf-8")
    assert payload["failures"][0]["cause"]["traceback"], "and the envelope is whole without it"


def test_a_classified_refusal_writes_no_dump(tmp_path: Path) -> None:
    """A read-only verb refusing must not create `.vqapr/` as a side effect."""
    payload = failure(_error(), project_root=tmp_path, stage=Stage.READ)

    assert "detail" not in payload
    assert not (tmp_path / ".vqapr").exists()


def test_a_dump_that_cannot_be_written_still_reports_the_failure(tmp_path: Path) -> None:
    """Rendering a failure must never destroy the failure."""
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")

    payload = failure(_raised(12), project_root=blocked, stage=Stage.RUN)

    assert payload["ok"] is False
    assert "detail" not in payload
    assert "RuntimeError" in payload["failures"][0]["cause"]["traceback"]


def test_the_declared_entry_point_builds_every_command() -> None:
    """`pyproject` promises `vqapr.cli.main:main`, so importing it must yield a usable parser."""
    from vqapr.cli.main import build_parser
    from vqapr.cli.main import main as entry_point

    assert callable(entry_point)
    actions = build_parser()._subparsers
    assert actions is not None
    rendered = build_parser().format_help()
    for command in ("new", "register", "run", "list"):
        assert command in rendered


def test_the_envelope_survives_a_legacy_console_encoding() -> None:
    """A cp949 console cannot encode an em dash, and losing the report there is not acceptable."""
    script = (
        "import sys;"
        "sys.path.insert(0, r'src');"
        "from vqapr.cli.envelope import emit;"
        "sys.exit(emit({'ok': False, 'error': 'em dash \\u2014 here'}))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        env={"PYTHONIOENCODING": "cp949"},
    )
    assert completed.returncode == 1
    assert json.loads(completed.stdout.decode("utf-8"))["error"].endswith("here")
