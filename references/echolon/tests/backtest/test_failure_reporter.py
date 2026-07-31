"""Unit tests for failure_reporter.

Covers the three public entry points:
  * aggregate() — fold individual OptimizationFailure records into groups
  * render_terminal() — human-readable stderr block
  * write_json_artifact() — AI-native JSON on disk

Scenarios:
  1. Many records collapsing into a single group (the common case — a
     single root bug causes all 1000 trials to fail the same way).
  2. Multiple distinct groups with stable top-N ordering.
  3. EchelonError metadata (error_code, context, docs_url) surviving the
     round-trip into the rendered output and JSON artifact.
"""
from __future__ import annotations

import json
from pathlib import Path

from echolon.backtest.engine.failure import OptimizationFailure
from echolon.backtest.optimization.failure_reporter import (
    FailureGroup,
    aggregate,
    render_terminal,
    write_json_artifact,
)


def _make_failure(msg: str, error_type: str = "ValueError", **ctx) -> OptimizationFailure:
    return OptimizationFailure(
        error_type=error_type,
        error_code=ctx.pop("error_code", None),
        message=msg,
        traceback=f"Traceback (most recent call last):\n  ...\n{error_type}: {msg}",
        context=ctx,
        trial_params={"entry_rsi": 30},
        docs_url=ctx.pop("docs_url", None),
    )


def test_aggregate_collapses_identical_failures_into_single_group():
    groups: dict = {}
    for i in range(50):
        aggregate(groups, _make_failure("schema rejected field 'cci_value'"), trial_number=i)

    assert len(groups) == 1
    g = next(iter(groups.values()))
    assert g.count == 50
    assert g.first_trial == 0
    assert g.last_trial == 49
    assert g.exemplar is not None
    # Exemplar preserved from the first occurrence.
    assert g.exemplar.message == "schema rejected field 'cci_value'"


def test_aggregate_preserves_distinct_groups():
    groups: dict = {}
    aggregate(groups, _make_failure("schema rejected field 'x'"), trial_number=0)
    aggregate(groups, _make_failure("schema rejected field 'x'"), trial_number=1)
    aggregate(groups, _make_failure("division by zero"), trial_number=2)
    aggregate(
        groups,
        _make_failure("unknown indicator", error_type="KeyError"),
        trial_number=3,
    )

    assert len(groups) == 3
    counts = sorted((g.count for g in groups.values()), reverse=True)
    assert counts == [2, 1, 1]


def test_render_terminal_includes_top_group_exemplar():
    groups: dict = {}
    for i in range(100):
        aggregate(groups, _make_failure("schema rejected 'cci_value'"), trial_number=i)
    for i in range(100, 110):
        aggregate(
            groups,
            _make_failure("zero division", error_type="ZeroDivisionError"),
            trial_number=i,
        )

    out = render_terminal(
        n_trials=110,
        n_failed=110,
        groups=groups.values(),
        window_id=3,
    )

    assert "110 of 110 trials failed" in out
    assert "window 3" in out
    # Top group comes first by count.
    top_pos = out.find("schema rejected 'cci_value'")
    bot_pos = out.find("zero division")
    assert 0 < top_pos < bot_pos
    assert "Exemplar traceback:" in out


def test_render_terminal_surfaces_echolon_error_metadata():
    groups: dict = {}
    failure = _make_failure(
        "VAL-002: entry_reason missing",
        error_type="EchelonError",
        error_code="VAL-002",
        docs_url="https://docs.echolon.dev/errors/VAL-002",
        component="entry",
        expected="entry_reason",
    )
    aggregate(groups, failure, trial_number=0)

    out = render_terminal(n_trials=1, n_failed=1, groups=groups.values())

    assert "[VAL-002]" in out
    assert "docs.echolon.dev/errors/VAL-002" in out
    assert "component=entry" in out


def test_render_terminal_empty_when_no_failures():
    # The caller should guard, but the function must not blow up if it doesn't.
    out = render_terminal(n_trials=100, n_failed=0, groups=[])
    assert out == ""


def test_render_terminal_suppresses_remainder_beyond_top_n():
    groups: dict = {}
    for i, msg in enumerate(["a", "b", "c", "d", "e"]):
        aggregate(groups, _make_failure(msg), trial_number=i)

    out = render_terminal(n_trials=5, n_failed=5, groups=groups.values(), top_n=2)

    assert "2 additional group(s) suppressed" in out or "3 additional group(s) suppressed" in out


def test_write_json_artifact_round_trips(tmp_path: Path):
    groups: dict = {}
    for i in range(30):
        aggregate(groups, _make_failure("err_a"), trial_number=i)
    for i in range(30, 35):
        aggregate(groups, _make_failure("err_b"), trial_number=i)

    out_path = tmp_path / "trial_failure_summary.json"
    write_json_artifact(
        out_path=out_path,
        n_trials=200,
        n_failed=35,
        n_complete=165,
        groups=groups.values(),
        window_id=1,
    )

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["window_id"] == 1
    assert payload["n_trials"] == 200
    assert payload["n_failed"] == 35
    assert payload["n_complete"] == 165
    assert abs(payload["failure_rate"] - 35 / 200) < 1e-9
    # Groups ordered by count descending.
    assert payload["groups"][0]["count"] == 30
    assert payload["groups"][1]["count"] == 5
    # Error record structure preserved.
    err = payload["groups"][0]["error"]
    assert err["error_type"] == "ValueError"
    assert err["message"] == "err_a"


def test_write_json_artifact_creates_parent_dir(tmp_path: Path):
    # Artifacts land in per-window subdirs that may not exist yet.
    out_path = tmp_path / "window_1" / "nested" / "trial_failure_summary.json"
    write_json_artifact(
        out_path=out_path,
        n_trials=1,
        n_failed=0,
        n_complete=1,
        groups=[],
    )
    assert out_path.exists()
