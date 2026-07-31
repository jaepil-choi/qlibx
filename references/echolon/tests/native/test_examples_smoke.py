"""End-to-end smoke test for bundled example strategies.

Phase F-6: catches the class of bug where a strategy declares column ``X`` in
``strategy_indicator_list.json`` but its component code looks up column ``Y``.
Existing schema-roundtrip tests (``test_examples_and_templates_validate.py``)
catch JSON-side typos but not code/JSON mismatches.

Approach: load each example's components dynamically against a stub
``ITradingEngine`` that exposes a controlled indicator map. Then exercise the
declared indicator names (the same suffixes ``processor._build_suffix`` will
emit at runtime) and assert that:

  * minimal: entry returns HOLD (no-op scaffold; never trades).
  * momentum_breakout: entry returns LONG when close breaks the declared
    ``highest_high_*`` column; exit returns should_exit=True when close drops
    below the declared ``lowest_low_*`` column.
  * rsi_mean_reversion: entry returns LONG when ``rsi_*`` column < oversold;
    exit returns should_exit=True when ``rsi_*`` column > overbought.

If an example's code asks for a column the JSON didn't declare, the stub
``get_indicator`` raises KeyError and the test fails — which is the regression
guard.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from echolon.strategy.interfaces import Position


_EXAMPLES_ROOT = (
    Path(__file__).resolve().parents[2]
    / "echolon" / "native" / "templates"
)


# ---------------------------------------------------------------------------
# Stubs implementing the slice of ITradingEngine that BaseComponent touches
# during entry/exit evaluation.
# ---------------------------------------------------------------------------


class _StubMarketData:
    def __init__(self, indicators: dict[str, float], price: float) -> None:
        self._indicators = {k.lower(): v for k, v in indicators.items()}
        self._price = price

    def get_current_price(self) -> float:
        return self._price

    def get_indicator(self, name: str, index: int = 0) -> float:
        key = name.lower()
        if key not in self._indicators:
            raise KeyError(f"Indicator not found: {name}")
        return self._indicators[key]


class _StubPortfolio:
    def __init__(self, position: Position | None = None) -> None:
        self._position = position

    def get_position(self) -> Position | None:
        return self._position


class _StubEngine:
    def __init__(self, market_data: _StubMarketData, portfolio: _StubPortfolio) -> None:
        self._md = market_data
        self._port = portfolio

    def get_market_data(self):
        return self._md

    def get_portfolio(self):
        return self._port

    def get_logger(self):
        return None

    def get_strategy_logger(self):
        return None

    def get_event_bus(self):
        return None

    def get_market_adapter(self):
        return None

    def get_frequency_context(self):
        return None

    def get_trading_context(self):
        return None


def _load_module(example_dir: Path, module_name: str) -> ModuleType:
    """Import ``<example_dir>/<module_name>.py`` as a uniquely-named module.

    Each example ships modules with the same names (entry, exit, ...). Using
    ``spec_from_file_location`` with example-namespaced names avoids
    ``sys.modules`` collisions across examples in the same test process.
    """
    path = example_dir / f"{module_name}.py"
    qualified = f"_example_{example_dir.name}_{module_name}"
    spec = importlib.util.spec_from_file_location(qualified, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


def _build_engine(indicators: dict[str, float], price: float, position: Position | None = None) -> _StubEngine:
    return _StubEngine(_StubMarketData(indicators, price), _StubPortfolio(position))


def _make_long_position(size: float = 1.0, avg_price: float = 100.0) -> Position:
    return Position(
        symbol="test", size=size, avg_price=avg_price,
        market_value=size * avg_price, unrealized_pnl=0.0, realized_pnl=0.0,
        direction="LONG",
    )


def _declared_columns(example_dir: Path) -> dict[str, Any]:
    """Read ``strategy_indicator_list.json`` and return the raw flat dict."""
    return json.loads((example_dir / "strategy_indicator_list.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 01_minimal: HOLD-forever scaffold — verifies the engine wiring without trading.
# ---------------------------------------------------------------------------


def test_01_minimal_imports_cleanly() -> None:
    example = _EXAMPLES_ROOT / "minimal"
    _load_module(example, "strategy")
    _load_module(example, "entry")
    _load_module(example, "exit")
    _load_module(example, "risk")
    _load_module(example, "sizer")


def test_01_minimal_entry_returns_hold() -> None:
    example = _EXAMPLES_ROOT / "minimal"
    entry_mod = _load_module(example, "entry")
    engine = _build_engine(indicators={}, price=100.0)
    component = entry_mod.entry_rule(trading_engine=engine, run_context="optimization", printlog=False)
    out = component.generate_signal()
    assert out.signal == "HOLD"
    assert out.intent is None


# ---------------------------------------------------------------------------
# 02_momentum_breakout: entry triggers on highest_high break; exit on lowest_low.
# ---------------------------------------------------------------------------


def test_02_momentum_breakout_columns_match_declaration() -> None:
    """Sanity guard: JSON still declares ``highest_high`` and ``lowest_low`` —
    if someone renames these, the column-name f-strings in entry/exit must
    follow."""
    declared = _declared_columns(_EXAMPLES_ROOT / "momentum_breakout")
    assert "highest_high" in declared
    assert "lowest_low" in declared


def _mb_indicators(lookback: int = 20, *, high: float, low: float) -> dict[str, float]:
    """Build the indicator map momentum_breakout's two-sided entry/exit reads.

    Both ``highest_high_N`` and ``lowest_low_N`` are queried each bar — the
    stub must provide both, otherwise the entry's ``lowest_low`` lookup
    KeyErrors before the LONG-side check resolves.
    """
    return {f"highest_high_{lookback}": high, f"lowest_low_{lookback}": low}


def test_02_momentum_breakout_entry_long_on_breakout() -> None:
    example = _EXAMPLES_ROOT / "momentum_breakout"
    entry_mod = _load_module(example, "entry")
    engine = _build_engine(
        indicators=_mb_indicators(20, high=100.0, low=80.0),
        price=101.0,  # > prior 20-bar high → LONG
    )
    component = entry_mod.entry_rule(
        trading_engine=engine, run_context="optimization",
        printlog=False, lookback=20,
    )
    out = component.generate_signal()
    assert out.signal == "LONG"
    assert out.intent is not None
    assert out.intent.value == "ENTRY_LONG"


def test_02_momentum_breakout_entry_short_on_breakdown() -> None:
    """New SHORT pathway: close < prior N-bar low."""
    example = _EXAMPLES_ROOT / "momentum_breakout"
    entry_mod = _load_module(example, "entry")
    engine = _build_engine(
        indicators=_mb_indicators(20, high=100.0, low=80.0),
        price=79.0,  # < prior 20-bar low → SHORT
    )
    component = entry_mod.entry_rule(
        trading_engine=engine, run_context="optimization",
        printlog=False, lookback=20,
    )
    out = component.generate_signal()
    assert out.signal == "SHORT"
    assert out.intent is not None
    assert out.intent.value == "ENTRY_SHORT"


def test_02_momentum_breakout_entry_hold_inside_channel() -> None:
    example = _EXAMPLES_ROOT / "momentum_breakout"
    entry_mod = _load_module(example, "entry")
    engine = _build_engine(
        indicators=_mb_indicators(20, high=100.0, low=80.0),
        price=90.0,  # inside the channel → HOLD
    )
    component = entry_mod.entry_rule(
        trading_engine=engine, run_context="optimization",
        printlog=False, lookback=20,
    )
    out = component.generate_signal()
    assert out.signal == "HOLD"


def test_02_momentum_breakout_exit_long_on_breakdown() -> None:
    example = _EXAMPLES_ROOT / "momentum_breakout"
    exit_mod = _load_module(example, "exit")
    engine = _build_engine(
        indicators=_mb_indicators(10, high=105.0, low=95.0),
        price=94.0,  # < prior 10-bar low → exit LONG
        position=_make_long_position(),
    )
    component = exit_mod.exit_rule(
        trading_engine=engine, run_context="optimization",
        printlog=False, exit_lookback=10,
    )
    out = component.should_exit()
    assert out.should_exit is True
    assert out.intent is not None
    assert out.intent.value == "EXIT_LONG"


def test_02_momentum_breakout_exit_short_on_breakout() -> None:
    """New SHORT exit pathway: close > prior N-bar high while short."""
    example = _EXAMPLES_ROOT / "momentum_breakout"
    exit_mod = _load_module(example, "exit")
    engine = _build_engine(
        indicators=_mb_indicators(10, high=105.0, low=95.0),
        price=106.0,  # > prior 10-bar high → exit SHORT
        position=Position(
            symbol="test", size=-1.0, avg_price=100.0,
            market_value=-100.0, unrealized_pnl=0.0, realized_pnl=0.0,
            direction="SHORT",
        ),
    )
    component = exit_mod.exit_rule(
        trading_engine=engine, run_context="optimization",
        printlog=False, exit_lookback=10,
    )
    out = component.should_exit()
    assert out.should_exit is True
    assert out.intent is not None
    assert out.intent.value == "EXIT_SHORT"


def test_02_momentum_breakout_exit_holds_inside_channel() -> None:
    example = _EXAMPLES_ROOT / "momentum_breakout"
    exit_mod = _load_module(example, "exit")
    engine = _build_engine(
        indicators=_mb_indicators(10, high=105.0, low=95.0),
        price=100.0,  # inside the channel → keep holding
        position=_make_long_position(),
    )
    component = exit_mod.exit_rule(
        trading_engine=engine, run_context="optimization",
        printlog=False, exit_lookback=10,
    )
    out = component.should_exit()
    assert out.should_exit is False


def test_02_momentum_breakout_entry_uses_declared_lookback_range() -> None:
    """Optuna sweeps ``lookback`` over [10, 50] per strategy_params.py — every
    column in that range must be reachable. Tests the bounds of the swept range
    against ``processor._build_suffix`` output."""
    example = _EXAMPLES_ROOT / "momentum_breakout"
    entry_mod = _load_module(example, "entry")
    for lookback in (10, 25, 50):
        engine = _build_engine(
            indicators=_mb_indicators(lookback, high=100.0, low=80.0),
            price=101.0,  # LONG breakout
        )
        component = entry_mod.entry_rule(
            trading_engine=engine, run_context="optimization",
            printlog=False, lookback=lookback,
        )
        out = component.generate_signal()
        assert out.signal == "LONG", f"lookback={lookback} should produce LONG"


# ---------------------------------------------------------------------------
# 03_rsi_mean_reversion: entry on RSI<oversold; exit on RSI>overbought.
# ---------------------------------------------------------------------------


def test_03_rsi_columns_match_declaration() -> None:
    declared = _declared_columns(_EXAMPLES_ROOT / "rsi_mean_reversion")
    assert "rsi" in declared


_RSI_PARAMS = {"rsi_period": 14, "oversold": 30, "overbought": 70}


def test_03_rsi_entry_long_when_oversold() -> None:
    example = _EXAMPLES_ROOT / "rsi_mean_reversion"
    entry_mod = _load_module(example, "entry")
    engine = _build_engine(indicators={"rsi_14": 25.0}, price=100.0)
    component = entry_mod.entry_rule(
        trading_engine=engine, run_context="optimization",
        printlog=False, **_RSI_PARAMS,
    )
    out = component.generate_signal()
    assert out.signal == "LONG"
    assert out.intent.value == "ENTRY_LONG"


def test_03_rsi_entry_short_when_overbought() -> None:
    """New SHORT pathway: RSI > overbought."""
    example = _EXAMPLES_ROOT / "rsi_mean_reversion"
    entry_mod = _load_module(example, "entry")
    engine = _build_engine(indicators={"rsi_14": 75.0}, price=100.0)
    component = entry_mod.entry_rule(
        trading_engine=engine, run_context="optimization",
        printlog=False, **_RSI_PARAMS,
    )
    out = component.generate_signal()
    assert out.signal == "SHORT"
    assert out.intent.value == "ENTRY_SHORT"


def test_03_rsi_entry_holds_when_in_neutral_zone() -> None:
    example = _EXAMPLES_ROOT / "rsi_mean_reversion"
    entry_mod = _load_module(example, "entry")
    engine = _build_engine(indicators={"rsi_14": 50.0}, price=100.0)
    component = entry_mod.entry_rule(
        trading_engine=engine, run_context="optimization",
        printlog=False, **_RSI_PARAMS,
    )
    out = component.generate_signal()
    assert out.signal == "HOLD"


def test_03_rsi_exit_long_when_overbought() -> None:
    example = _EXAMPLES_ROOT / "rsi_mean_reversion"
    exit_mod = _load_module(example, "exit")
    engine = _build_engine(
        indicators={"rsi_14": 75.0}, price=100.0,
        position=_make_long_position(),
    )
    component = exit_mod.exit_rule(
        trading_engine=engine, run_context="optimization",
        printlog=False, **_RSI_PARAMS,
    )
    out = component.should_exit()
    assert out.should_exit is True
    assert out.intent.value == "EXIT_LONG"


def test_03_rsi_exit_short_when_oversold() -> None:
    """New SHORT exit pathway: RSI < oversold while short."""
    example = _EXAMPLES_ROOT / "rsi_mean_reversion"
    exit_mod = _load_module(example, "exit")
    engine = _build_engine(
        indicators={"rsi_14": 25.0}, price=100.0,
        position=Position(
            symbol="test", size=-1.0, avg_price=100.0,
            market_value=-100.0, unrealized_pnl=0.0, realized_pnl=0.0,
            direction="SHORT",
        ),
    )
    component = exit_mod.exit_rule(
        trading_engine=engine, run_context="optimization",
        printlog=False, **_RSI_PARAMS,
    )
    out = component.should_exit()
    assert out.should_exit is True
    assert out.intent.value == "EXIT_SHORT"


def test_03_rsi_entry_uses_declared_period_range() -> None:
    """JSON declares ``timeperiod=[10,20]`` and Optuna sweeps the same range —
    column lookups must succeed across the full sweep."""
    example = _EXAMPLES_ROOT / "rsi_mean_reversion"
    entry_mod = _load_module(example, "entry")
    for period in (10, 14, 20):
        engine = _build_engine(indicators={f"rsi_{period}": 25.0}, price=100.0)
        component = entry_mod.entry_rule(
            trading_engine=engine, run_context="optimization",
            printlog=False, rsi_period=period, oversold=30, overbought=70,
        )
        out = component.generate_signal()
        assert out.signal == "LONG", f"rsi_period={period} should produce LONG when RSI=25"


# ---------------------------------------------------------------------------
# Negative cases — column-name typos surface as KeyError, not silent HOLD.
# ---------------------------------------------------------------------------


def test_02_momentum_breakout_raises_on_missing_column() -> None:
    """If the JSON ↔ code naming drifts, ``get_indicator`` must raise — the
    Phase F-6 fix removed the try/except that previously masked this bug."""
    example = _EXAMPLES_ROOT / "momentum_breakout"
    entry_mod = _load_module(example, "entry")
    engine = _build_engine(indicators={"high_20": 100.0}, price=101.0)  # WRONG name
    component = entry_mod.entry_rule(
        trading_engine=engine, run_context="optimization",
        printlog=False, lookback=20,
    )
    with pytest.raises(KeyError):
        component.generate_signal()


def test_03_rsi_raises_on_missing_column() -> None:
    example = _EXAMPLES_ROOT / "rsi_mean_reversion"
    entry_mod = _load_module(example, "entry")
    engine = _build_engine(indicators={"rsi": 25.0}, price=100.0)  # bare name, missing _14
    component = entry_mod.entry_rule(
        trading_engine=engine, run_context="optimization",
        printlog=False, rsi_period=14, oversold=30, overbought=70,
    )
    with pytest.raises(KeyError):
        component.generate_signal()
