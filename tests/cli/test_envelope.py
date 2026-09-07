"""The envelope is the agent's only parsing contract, so its shape is protected here."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from vqapr.cli.envelope import MAX_INLINE_TRACEBACK_LINES, failure, success
from vqapr.domain.errors import (
    ExplainTopic,
    Failure,
    FailureFamily,
    FailureSource,
    VqaprError,
)


def _error() -> VqaprError:
    return VqaprError(
        stage="component.load",
        family=FailureFamily.DATA,
        failures=[
            Failure.bounded(
                "component.load.wrong_type",
                "must implement",
                observed="S",
                source=FailureSource(file="strategies.py", key_path="UserStrategy", line=12),
                fix="subclass StrategyModel, then register the component again",
                explain=ExplainTopic.COMPONENT_CONTRACT,
            )
        ],
        mutation=False,
        retry_precondition="fix and register the component again, then retry",
    )


def test_success_and_failure_share_their_envelope_keys() -> None:
    """An agent must not need to know which outcome it got before parsing it."""
    ok = success("component.register", id="x")
    bad = failure(_error())
    assert ok["ok"] is True
    assert bad["ok"] is False
    assert {"ok", "stage"} <= set(ok)
    assert {"ok", "stage"} <= set(bad)


def test_failure_preserves_the_package_verdict_verbatim() -> None:
    """The CLI must not invent stage, code, or remedy text of its own."""
    payload = failure(_error())
    assert payload["stage"] == "component.load"
    assert payload["family"] == "DATA"
    assert payload["failures"][0]["code"] == "component.load.wrong_type"
    assert payload["retry_precondition"] == "fix and register the component again, then retry"


def test_every_envelope_field_survives_a_json_round_trip() -> None:
    """The envelope is the agent's only parsing contract, so it must survive serialization whole.

    A field that renders but does not round-trip is worse than a missing one: it reads correctly
    in a log and arrives as something else in the consumer. `source` is the field at risk, because
    it is the only nested structure in the payload.
    """
    payload = failure(_error())
    restored = json.loads(json.dumps(payload))

    assert restored == payload, "the envelope did not survive a JSON round trip unchanged"

    entry = restored["failures"][0]
    assert entry["fix"] == "subclass StrategyModel, then register the component again"
    assert entry["explain"] == "component-contract"
    # `source` stays a structure. Flattening it to "strategies.py:12" would force every consumer to
    # write a regex, and that regex would break silently the day the format changed.
    assert entry["source"] == {"file": "strategies.py", "key_path": "UserStrategy", "line": 12}


def test_a_refusal_carries_all_six_envelope_fields() -> None:
    """An agent parses these by name, so every one of them must be present and populated."""
    entry = failure(_error())["failures"][0]

    for field in ("code", "source", "requirement", "observed", "fix", "explain"):
        assert field in entry, f"the envelope lost {field!r}"
    for field in ("code", "requirement", "fix", "explain"):
        assert entry[field], f"{field!r} is present but empty, which tells the reader nothing"


def test_an_absent_location_says_so_rather_than_inventing_one() -> None:
    """Not every refusal has a file or a line, and guessing one would send the reader somewhere."""
    unlocated = VqaprError(
        stage="preflight.account",
        family=FailureFamily.ACCOUNT,
        failures=[
            Failure.bounded(
                "preflight.account.mode",
                "a long-only account must not hold a short",
                observed="A005930: -10",
                fix="drop the short holding, or declare the account SIGNED",
                explain=ExplainTopic.RUN_PRECONDITION,
            )
        ],
    )

    source = failure(unlocated)["failures"][0]["source"]

    assert source == {"file": None, "key_path": None, "line": None}


def test_a_short_traceback_stays_inline(tmp_path: Path) -> None:
    payload = failure(ValueError("small"), project_root=tmp_path)
    assert "detail" not in payload
    assert not (tmp_path / ".vqapr" / "diagnostics").exists()


def test_an_oversized_traceback_moves_to_a_dump(tmp_path: Path) -> None:
    def deep(n: int) -> None:
        if n == 0:
            raise RuntimeError("bottom")
        deep(n - 1)

    try:
        deep(MAX_INLINE_TRACEBACK_LINES + 5)
    except RuntimeError as error:
        payload = failure(error, project_root=tmp_path)

    detail = payload["detail"]
    assert detail is not None
    written = Path(detail)
    assert written.exists()
    assert "RuntimeError" in written.read_text(encoding="utf-8")


def test_a_dump_that_cannot_be_written_still_reports_the_failure(tmp_path: Path) -> None:
    """Rendering a failure must never destroy the failure."""

    def deep(n: int) -> None:
        if n == 0:
            raise RuntimeError("bottom")
        deep(n - 1)

    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    try:
        deep(MAX_INLINE_TRACEBACK_LINES + 5)
    except RuntimeError as error:
        payload = failure(error, project_root=blocked)

    assert payload["ok"] is False
    assert "RuntimeError" in payload["traceback"]


def test_the_declared_entry_point_builds_every_command() -> None:
    """`pyproject` promises `vqapr.cli.main:main`, so importing it must yield a usable parser."""
    from vqapr.cli.main import main as entry_point
    from vqapr.cli.main import build_parser

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
