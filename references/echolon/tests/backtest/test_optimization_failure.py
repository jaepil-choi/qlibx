"""Unit tests for OptimizationFailure + OptimizationMetrics.failed_from_exc.

Covers the worker-side capture path that the controller later consumes:

    raise in Strategy.on_bar
        ↓ (caught in OptimizationRunner.run_trial)
    OptimizationMetrics.failed_from_exc(e, trial_params)
        ↓ (invokes)
    OptimizationFailure.from_exception(e, trial_params)
        ↓ (returned from worker process as serializable dict)
    failure.to_dict()
        ↓ (controller-side)
    OptimizationFailure(**failure_dict)
        ↓ (folded into)
    failure_reporter.aggregate(groups, failure, trial_number)

This test file verifies the middle three steps. The aggregate/render/JSON
legs are covered by ``test_failure_reporter.py``; the IPC boundary itself
(ProcessPoolExecutor pickling the dict) is implicit in the OS/stdlib.
"""
from __future__ import annotations

import pytest

from echolon.backtest.engine.failure import OptimizationFailure
from echolon.backtest.engine.optimization_runner import OptimizationMetrics
from echolon.errors import EchelonError, raise_error


def _raise_and_capture(exc_cls, *args, **kwargs):
    """Raise ``exc_cls(*args, **kwargs)`` and return the caught instance."""
    try:
        raise exc_cls(*args, **kwargs)
    except exc_cls as e:
        return e


def _raise_and_capture_from(callable_):
    """Invoke ``callable_()`` expecting it to raise, and return the instance."""
    try:
        callable_()
    except BaseException as e:  # noqa: BLE001 — any exception is the point
        return e
    raise AssertionError("expected an exception, got none")


def test_from_exception_captures_vanilla_exception():
    e = _raise_and_capture(ValueError, "bad param value")
    f = OptimizationFailure.from_exception(e, trial_params={"rsi": 30})

    assert f.error_type == "ValueError"
    assert f.error_code is None
    assert "bad param value" in f.message
    assert f.trial_params == {"rsi": 30}
    assert f.traceback  # non-empty
    assert "ValueError" in f.traceback


def test_from_exception_captures_echolon_error_metadata():
    e = _raise_and_capture(
        EchelonError,
        code="VAL-002",
        what="Missing required field",
        why="entry_reason is required",
        fix="Add entry_reason to EntrySignalOutput(...)",
        context={"component": "entry", "expected": "entry_reason"},
        docs_url="https://echolon.dev/docs/errors/VAL-002",
    )
    f = OptimizationFailure.from_exception(e, trial_params={"x": 1})

    assert f.error_type == "EchelonError"
    assert f.error_code == "VAL-002"
    assert f.context == {"component": "entry", "expected": "entry_reason"}
    assert f.docs_url == "https://echolon.dev/docs/errors/VAL-002"


def test_from_exception_caps_message_length():
    from echolon.backtest.engine.failure import _MSG_MAX_CHARS

    huge = "x" * 5000
    e = _raise_and_capture(ValueError, huge)
    f = OptimizationFailure.from_exception(e, trial_params={})

    # Capped at _MSG_MAX_CHARS + 1 char for the ellipsis suffix.
    assert len(f.message) <= _MSG_MAX_CHARS + 1
    # Verify truncation actually happened (the cap is active, not no-op).
    assert f.message.endswith("…")
    assert len(f.message) < 5000


def test_from_exception_caps_traceback_size():
    # Build a reasonably deep traceback by nesting calls.
    def recurse(n):
        if n == 0:
            raise RuntimeError("deep")
        return recurse(n - 1)

    try:
        recurse(400)
    except RuntimeError as e:
        f = OptimizationFailure.from_exception(e, trial_params={})

    # Traceback capped at 4096 chars per TB_MAX_CHARS.
    assert len(f.traceback) <= 4096
    # Tail-truncated, so the actual raise site survives.
    assert "RuntimeError" in f.traceback


def test_to_dict_round_trip_preserves_all_fields():
    e = _raise_and_capture(
        EchelonError,
        code="BT-001",
        what="Strategy.on_bar raised",
        why="component threw",
        fix="inspect component",
        context={"bar_index": 42, "contract": "al2501"},
        docs_url="https://echolon.dev/docs/errors/BT-001",
    )
    original = OptimizationFailure.from_exception(
        e, trial_params={"entry_rsi": 25, "exit_atr": 2.0},
    )

    as_dict = original.to_dict()
    # Simulate ProcessPoolExecutor IPC: the dict is pickled + unpickled.
    # Structurally equivalent to what ``_run_parallel`` does:
    #   OptimizationFailure(**failure_dict)
    reconstructed = OptimizationFailure(**as_dict)

    assert reconstructed.error_type == original.error_type
    assert reconstructed.error_code == original.error_code
    assert reconstructed.message == original.message
    assert reconstructed.traceback == original.traceback
    assert reconstructed.context == original.context
    assert reconstructed.trial_params == original.trial_params
    assert reconstructed.docs_url == original.docs_url
    assert reconstructed.group_key() == original.group_key()


def test_group_key_is_stable_across_trial_param_changes():
    # Two trials with different params but identical exception should
    # collapse to the same group.
    e1 = _raise_and_capture(ValueError, "bad")
    e2 = _raise_and_capture(ValueError, "bad")
    f1 = OptimizationFailure.from_exception(e1, trial_params={"a": 1})
    f2 = OptimizationFailure.from_exception(e2, trial_params={"a": 999})

    assert f1.group_key() == f2.group_key()


def test_group_key_differs_on_different_error_types():
    f1 = OptimizationFailure.from_exception(
        _raise_and_capture(ValueError, "same msg"), trial_params={},
    )
    f2 = OptimizationFailure.from_exception(
        _raise_and_capture(KeyError, "same msg"), trial_params={},
    )
    assert f1.group_key() != f2.group_key()


def test_optimization_metrics_failed_from_exc():
    e = _raise_and_capture(KeyError, "missing indicator column 'cci'")
    metrics = OptimizationMetrics.failed_from_exc(e, trial_params={"p": 1})

    assert metrics.success is False
    assert metrics.failure is not None
    assert metrics.failure.error_type == "KeyError"
    assert "missing indicator column" in metrics.failure.message
    # Back-compat accessor still works.
    assert metrics.error_message == metrics.failure.message
    # Sentinel metric values set so Optuna's objective doesn't crash.
    assert metrics.sharpe_ratio == -1.0
    assert metrics.max_drawdown_pct == -999.0
    assert metrics.annual_return_pct == -100.0
    assert metrics.total_trades == 0


def test_optimization_metrics_failed_legacy_constructor():
    # The legacy ``failed(error_message)`` path survives for pre-condition
    # checks (``Shared data not initialized``, etc.) that don't have a
    # live exception to pass in.
    metrics = OptimizationMetrics.failed("Shared data not initialized")

    assert metrics.success is False
    assert metrics.failure is not None
    assert metrics.failure.error_type == "PreconditionError"
    assert metrics.failure.message == "Shared data not initialized"
    assert metrics.failure.trial_params == {}


def test_echolon_error_message_strips_leading_newline():
    """EchelonError.__str__ starts with '\\n' by design so the CLI block
    renders on its own line. Prior to the fix, ``message.splitlines()[0]``
    was '' for every EchelonError — the terminal summary showed
    ``Message:`` with nothing after it. Lock the strip behavior."""
    e = _raise_and_capture(
        EchelonError,
        code="BT-001",
        what="Strategy.on_bar raised",
        why="component threw",
        fix="inspect component",
        context={"component": "entry"},
        docs_url="https://echolon.dev/docs/errors/BT-001",
    )
    f = OptimizationFailure.from_exception(e, trial_params={})

    # First non-empty line must be the BT-001 tagline, not an empty string.
    first_line = f.message.splitlines()[0]
    assert first_line != ""
    assert "BT-001" in first_line


def test_traceback_contains_stack_frames_not_exception_self_description():
    """EchelonError's ``__str__`` is ~500 chars of what/why/fix decoration.
    ``traceback.format_exception`` appends that at the tail. With a 4KB
    cap, the tail-slice kept the decoration and threw away the stack
    frames — the captured traceback showed the error's own message twice
    instead of the Python stack. Lock the stack-frames-only capture."""
    def inner():
        raise_error(
            "BT-001",
            file="test",
            bar_index=0,
            trading_date="2026-04-24",
            contract="test",
            position_size=0,
            exception_repr="demo",
        )

    e = _raise_and_capture_from(inner)
    f = OptimizationFailure.from_exception(e, trial_params={})

    # Traceback must open with the canonical header.
    assert f.traceback.startswith("Traceback") or "…(traceback truncated)…" in f.traceback
    # Must contain at least one "File ..., line ..., in ..." frame.
    assert "File " in f.traceback
    assert "line " in f.traceback
    # Must NOT duplicate the EchelonError decoration that's already in .context + .docs_url.
    assert "Why:" not in f.traceback
    assert "Fix:" not in f.traceback


def test_optimization_metrics_failed_from_exc_serializable_end_to_end():
    """Full worker→controller path: exception → metrics → dict → reconstruct."""
    e = _raise_and_capture(
        EchelonError,
        code="IND-004",
        what="Degenerate regime result",
        why="all trials mapped to one regime",
        fix="widen param range",
        context={"regime_counts": {"trending_up": 100, "volatile": 0, "ranging": 0}},
        docs_url="https://echolon.dev/docs/errors/IND-004",
    )
    metrics = OptimizationMetrics.failed_from_exc(e, trial_params={"k": 42})

    # Simulate what ``run_optimization_trial`` returns + what _run_parallel reads.
    result_dict = {
        "success": False,
        "failure": metrics.failure.to_dict(),
        "critical_error": False,
    }

    # Controller-side reconstruction (mirrors _run_parallel line-for-line).
    failure_dict = result_dict["failure"]
    reconstructed = OptimizationFailure(**failure_dict)

    assert reconstructed.error_code == "IND-004"
    assert reconstructed.context["regime_counts"]["trending_up"] == 100
    assert reconstructed.trial_params == {"k": 42}
