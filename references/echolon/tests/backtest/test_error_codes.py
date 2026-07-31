"""Backtest-layer errors use BT-001/002/003 catalog codes via helper functions."""
import pytest

from echolon.errors import EchelonError


def test_wrap_on_bar_exception_raises_bt_001():
    """The helper re-raises a strategy exception as BT-001 with bar context."""
    from echolon.backtest.engine.backtrader_strategy import _wrap_on_bar_exception

    inner = KeyError("entry_rule")
    with pytest.raises(EchelonError) as exc:
        _wrap_on_bar_exception(
            exc=inner,
            bar_index=42,
            trading_date="2024-03-15",
            contract="al2403",
            position_size=0,
            file="entry.py",
        )
    assert exc.value.code == "BT-001"
    assert "al2403" in str(exc.value)
    assert "42" in str(exc.value)


def test_assert_trades_produced_raises_bt_002_on_zero():
    """The helper raises BT-002 when total_trades == 0."""
    from echolon.backtest.engine.backtest_runner import _assert_trades_produced

    with pytest.raises(EchelonError) as exc:
        _assert_trades_produced(
            total_trades=0,
            bars_processed=1000,
            entry_signals_generated=0,
            entry_signals_blocked=0,
            risk_blocks=0,
        )
    assert exc.value.code == "BT-002"


def test_assert_trades_produced_passes_when_nonzero():
    """The helper is a no-op when total_trades > 0."""
    from echolon.backtest.engine.backtest_runner import _assert_trades_produced

    # No raise
    _assert_trades_produced(total_trades=5, bars_processed=1000)


def test_raise_constraint_violation_raises_bt_003():
    """Helper raises BT-003 with trial params in context."""
    from echolon.backtest.optimization.optuna_study import _raise_constraint_violation

    with pytest.raises(EchelonError) as exc:
        _raise_constraint_violation(
            trial_number=12,
            constraint="MIN_RETURN_SEPARATION",
            required=0.001,
            actual=-0.0005,
            params={"entry_rsi": 30, "exit_atr": 2.0},
        )
    assert exc.value.code == "BT-003"
