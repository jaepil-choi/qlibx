"""Lock the ``extra='allow'`` contract on strategy component outputs.

Module + class docstrings in :mod:`echolon.strategy.schemas` advertise that
strategy components MAY attach diagnostic fields (indicator values, regime
context, etc.) to their outputs. ``SizerOutput`` + ``RiskOutput`` implement
this via ``class Config: extra = 'allow'``; ``EntrySignalOutput`` +
``ExitSignalOutput`` via ``ConfigDict(extra='allow', ...)``.

This test is a tripwire: previous regressions have silently flipped the
entry/exit schemas to ``extra='forbid'``, which causes every strategy that
follows the documented pattern to fail every bar with a ``ValidationError``.
Under Optuna those failures collapse into a silent ``n_failed == n_trials``
with no surfaced root cause. See
docs/superpowers/plans/2026-04-24-schema-extras-and-silent-optuna-failures.md
"""
import pytest

from echolon.strategy.schemas import (
    EntrySignalOutput,
    ExitSignalOutput,
    RiskOutput,
    SizerOutput,
)
from echolon.strategy.interfaces import OrderIntent


def test_entry_signal_output_accepts_extras() -> None:
    out = EntrySignalOutput(
        signal="LONG",
        strength=0.85,
        type="entry_long",
        entry_reason="test",
        intent=OrderIntent.ENTRY_LONG,
        regime="trending_up",
        # diagnostic extras — shape used by v6.1 SHFE aluminum strategies
        cci_value=141.92,
        rsi_value=55.3,
        custom_metric=0.42,
    )
    assert out.cci_value == 141.92
    assert out.rsi_value == 55.3
    assert out.custom_metric == 0.42


def test_exit_signal_output_accepts_extras() -> None:
    out = ExitSignalOutput(
        should_exit=False,
        exit_reason="holding",
        position_size=0.0,
        bars_since_entry=0,
        intent=None,
        regime="trending_up",
        # diagnostic extras
        stop_distance=35.0,
        trailing_stop=4550.0,
    )
    assert out.stop_distance == 35.0
    assert out.trailing_stop == 4550.0


def test_risk_output_accepts_extras() -> None:
    # RiskOutput already extra='allow' — lock the contract.
    out = RiskOutput(
        trading_allowed=True,
        risk_reason="within limits",
        # diagnostic extras
        current_drawdown=-2.3,
        circuit_breaker_armed=False,
    )
    assert out.current_drawdown == -2.3
    assert out.circuit_breaker_armed is False


def test_sizer_output_accepts_extras() -> None:
    # SizerOutput already extra='allow' — lock the contract.
    out = SizerOutput(
        calculated_size=3,
        signal_direction="LONG",
        sizing_reason="test",
        raw_size=3.2,
        # diagnostic extras
        atr_value=45.0,
        risk_per_trade_pct=2.0,
    )
    assert out.atr_value == 45.0
    assert out.risk_per_trade_pct == 2.0


def test_entry_signal_output_still_validates_required_fields() -> None:
    """extra='allow' must NOT relax required-field validation."""
    with pytest.raises(Exception) as exc_info:
        EntrySignalOutput(
            signal="LONG",
            # missing: strength, type, entry_reason, regime
            intent=None,
        )
    # Any validation error path is fine — we're just asserting required
    # fields still guard. VAL-001 is echolon's missing-fields code.
    assert exc_info.value is not None


def test_entry_signal_output_still_validates_enum() -> None:
    """extra='allow' must NOT relax signal-enum validation."""
    with pytest.raises(Exception):
        EntrySignalOutput(
            signal="BUY",  # invalid — must be LONG / SHORT / HOLD
            strength=0.5,
            type="entry",
            entry_reason="test",
            intent=None,
            regime="trending_up",
        )
