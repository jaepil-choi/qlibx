"""Regime-optional contract tests.

``EntrySignalOutput.regime`` is Optional. TRS-paradigm strategies populate
it; TSMOM and other paradigms can omit it.
"""
from __future__ import annotations

import pytest

from echolon.strategy.schemas import EntrySignalOutput
from echolon.strategy.interfaces import OrderIntent


def test_entry_signal_output_regime_is_optional() -> None:
    """Phase A: TSMOM strategies can omit regime entirely."""
    output = EntrySignalOutput(
        signal="LONG",
        strength=0.92,
        type="entry_long",
        entry_reason="momentum signal positive",
        intent=OrderIntent.ENTRY_LONG,
        # regime omitted intentionally
    )
    assert output.regime is None


def test_entry_signal_output_regime_still_accepted() -> None:
    """Phase A back-compat: TRS strategies still populate regime; field still accepts strings."""
    output = EntrySignalOutput(
        signal="LONG",
        strength=0.85,
        type="entry_long",
        entry_reason="trending up",
        intent=OrderIntent.ENTRY_LONG,
        regime="trending_up",
    )
    assert output.regime == "trending_up"


def test_entry_signal_output_regime_default_serializes_as_none() -> None:
    """Phase A: when regime is omitted, model_dump produces None (not the string 'None')."""
    output = EntrySignalOutput(
        signal="HOLD",
        strength=0.0,
        type="hold",
        entry_reason="no signal",
        intent=None,
    )
    payload = output.model_dump()
    assert "regime" in payload
    assert payload["regime"] is None


def test_hold_signal_without_regime() -> None:
    """Phase A: HOLD signal (most common scaffold default) parses cleanly without regime."""
    output = EntrySignalOutput(
        signal="HOLD",
        strength=0.0,
        type="hold",
        entry_reason="scaffold default",
        intent=None,
    )
    assert output.regime is None
    assert output.signal == "HOLD"


def test_entry_signal_output_explicit_regime_none() -> None:
    """Phase A: explicit regime=None is equivalent to omitting."""
    output = EntrySignalOutput(
        signal="SHORT",
        strength=0.7,
        type="entry_short",
        entry_reason="momentum negative",
        intent=OrderIntent.ENTRY_SHORT,
        regime=None,
    )
    assert output.regime is None
