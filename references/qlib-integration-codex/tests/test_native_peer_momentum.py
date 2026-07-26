from __future__ import annotations

import inspect

import pandas as pd
import pytest
from qlib.backtest.decision import Order
from qlib.strategy.base import BaseStrategy

from peer_momentum_runtime import QlibPeerMomentumStrategy
from peer_momentum_runtime.data import _build_position_unit_factor
from peer_momentum_runtime.exchange import KrxPandasExchange, build_quote_frame
from peer_momentum_runtime.peer_return import compute_peer_return
from peer_momentum_runtime import runner as qlib_runner


def test_peer_momentum_is_a_concrete_qlib_strategy() -> None:
    assert issubclass(QlibPeerMomentumStrategy, BaseStrategy)
    assert "generate_trade_decision" in QlibPeerMomentumStrategy.__dict__
    assert "post_exe_step" in QlibPeerMomentumStrategy.__dict__


def test_runner_does_not_precompute_peer_signal_or_target() -> None:
    runner_source = inspect.getsource(qlib_runner.run_qlib_peer_momentum)
    strategy_source = inspect.getsource(
        QlibPeerMomentumStrategy.generate_trade_decision
    )

    assert "compute_peer_return" not in runner_source
    assert "physical_target" not in runner_source
    assert "compute_peer_return" in strategy_source
    assert "TradeDecisionWO" in strategy_source


def test_peer_return_twin_is_independent_leave_one_out_calculation() -> None:
    index = pd.Index(["A", "B", "C", "D"])
    returns = pd.Series([0.10, 0.20, -0.10, 0.30], index=index)
    groups = pd.Series([1, 1, 2, 3], index=index)
    universe = pd.Series([True, True, True, False], index=index)

    signal = compute_peer_return(returns, groups, universe)

    assert signal["A"] == pytest.approx(0.20)
    assert signal["B"] == pytest.approx(0.10)
    assert pd.isna(signal["C"])
    assert pd.isna(signal["D"])


def test_native_twin_does_not_import_src_peer_return_implementation() -> None:
    strategy_source = inspect.getsource(QlibPeerMomentumStrategy)
    peer_return_source = inspect.getsource(compute_peer_return)

    forbidden = (
        "kwam_enhanced_index.strategies.peer_momentum",
        "kwam_enhanced_index.research.peer_momentum",
    )
    assert all(name not in strategy_source for name in forbidden)
    assert all(name not in peer_return_source for name in forbidden)


def test_twin_builds_position_factor_without_production_etf_preprocessing() -> None:
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    adjustment = pd.DataFrame({"A": [0.0, 2.0, 1.0]}, index=dates)

    factor = _build_position_unit_factor(adjustment)

    assert factor.loc[dates[0], "A"] == pytest.approx(0.5)
    assert factor.loc[dates[1], "A"] == pytest.approx(1.0)
    assert factor.loc[dates[2], "A"] == pytest.approx(1.0)


def test_quote_frame_allows_universe_exit_at_valid_suspension_mark() -> None:
    dates = pd.to_datetime(["2023-01-30"])
    columns = pd.Index(["A"])
    price = pd.DataFrame([[51_600.0]], index=dates, columns=columns)
    factor = pd.DataFrame(1.0, index=dates, columns=columns)
    volume = pd.DataFrame(0.0, index=dates, columns=columns)
    buyable = pd.DataFrame(False, index=dates, columns=columns)
    sellable = pd.DataFrame(True, index=dates, columns=columns)
    suspended = pd.DataFrame(True, index=dates, columns=columns)

    quote = build_quote_frame(
        price,
        factor,
        volume,
        buyable,
        sellable,
        suspended,
        max_volume_participation=0.10,
    )
    row = quote.loc[("A", dates[0])]

    assert bool(row["$limit_buy"])
    assert not bool(row["$limit_sell"])
    assert row["$volume_limit"] == pytest.approx(float("inf"))
    assert row["$close"] == pytest.approx(51_600.0)


def test_exchange_generic_tradability_preserves_sell_only_exit(monkeypatch) -> None:
    exchange = object.__new__(KrxPandasExchange)
    monkeypatch.setattr(exchange, "check_stock_suspended", lambda *_args: False)
    monkeypatch.setattr(
        exchange,
        "check_stock_limit",
        lambda _stock, _start, _end, direction=None: direction == Order.BUY,
    )
    date = pd.Timestamp("2023-01-30")

    assert exchange.is_stock_tradable("A", date, date)
    assert not exchange.is_stock_tradable("A", date, date, Order.BUY)
    assert exchange.is_stock_tradable("A", date, date, Order.SELL)
