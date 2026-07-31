"""P1 cost-model end-to-end tests.

These tests exercise real Backtrader/Cerebro execution paths instead of source
inspection. They are intentionally small and synthetic so the expected costs can
be computed by hand from plans/SPECS.md S11.
"""
from __future__ import annotations

import backtrader as bt
import pandas as pd
import pytest

from echolon.backtest.engine.backtrader_engine import BacktraderEngine
from echolon.backtest.engine.hooks.base import NullHook
from echolon.config.markets.factory import MarketFactory
from echolon.config.markets.shfe.instruments import get_instrument
from echolon.markets.interface import ContractSpec
from echolon.strategy.frequency.interday_context import InterdayContext


MONEY_TOLERANCE_RMB = 0.01


def _s11_al_dataframe() -> pd.DataFrame:
    dates = pd.to_datetime(
        [
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
            "2024-01-08",
            "2024-01-09",
            "2024-01-10",
            "2024-01-11",
            "2024-01-12",
            "2024-01-15",
        ]
    )
    closes = [19000 + 10 * index for index in range(len(dates))]
    opens = [closes[0], *closes[:-1]]
    return pd.DataFrame(
        {
            "open": opens,
            "high": [value + 100 for value in opens],
            "low": [value - 100 for value in opens],
            "close": closes,
            "volume": [1000] * len(dates),
        },
        index=dates,
    )


class _OneLotMarketEntryOnBarThree(bt.Strategy):
    params = (
        ("engine", None),
        ("strategy_name", "p1_cost_e2e"),
        ("market", "SHFE"),
        ("instrument", "aluminum"),
        ("instrument_code", "al"),
        ("strategy_params", {}),
        ("printlog", False),
    )

    executions: list[dict[str, float]] = []

    def __init__(self) -> None:
        self._submitted = False

    def next(self) -> None:
        if len(self) == 3 and not self._submitted:
            self._submitted = True
            self.buy(size=1)

    def notify_order(self, order: bt.Order) -> None:
        if order.status == order.Completed:
            self.executions.append(
                {
                    "price": float(order.executed.price),
                    "size": float(order.executed.size),
                    "commission": float(order.executed.comm),
                }
            )


class _FinalBrokerReplacingHook(NullHook):
    @property
    def name(self) -> str:
        return "FinalBrokerReplacingHook"

    def on_setup(self, cerebro: bt.Cerebro, engine: BacktraderEngine) -> None:
        replacement = bt.brokers.BackBroker()
        replacement.setcash(engine._initial_cash)
        spec = engine.get_market_adapter().get_contract_spec("al")
        replacement.setcommission(
            commission=spec.commission,
            commtype=bt.CommInfoBase.COMM_FIXED,
            mult=spec.multiplier,
        )
        cerebro.setbroker(replacement)


class _StaticSHFEAdapter:
    market_code = "SHFE"

    def __init__(self, contract_spec: ContractSpec) -> None:
        self._contract_spec = contract_spec

    def get_contract_spec(self, symbol: str) -> ContractSpec:
        assert symbol == "al"
        return self._contract_spec


def _al_contract_spec_with_three_bps_slippage() -> ContractSpec:
    instrument = get_instrument("al")
    return ContractSpec(
        symbol="al",
        multiplier=instrument.multiplier,
        tick_size=instrument.tick_size,
        margin_rate=instrument.margin_rate,
        commission=instrument.commission,
        commission_type=instrument.commission_type,
        calibrated_slippage_bps=3.0,
    )


def test_which_slippage_tier_runs() -> None:
    """A hook-replaced final broker must still apply the v1 3 bps tier."""
    _OneLotMarketEntryOnBarThree.executions = []
    contract_spec = _al_contract_spec_with_three_bps_slippage()
    ctx = MarketFactory.create(
        market="SHFE",
        instrument="al",
        frequency="interday",
        bar_size="1d",
        initial_capital=200_000.0,
    )
    data_feed = bt.feeds.PandasData(dataname=_s11_al_dataframe())
    engine = BacktraderEngine(
        ctx=ctx,
        market_adapter=_StaticSHFEAdapter(contract_spec),
        frequency_context=InterdayContext(),
        strategy_logger_enabled=False,
    )
    engine.add_hook(_FinalBrokerReplacingHook())

    engine.setup(data_feed, _OneLotMarketEntryOnBarThree)
    engine.run()

    assert len(_OneLotMarketEntryOnBarThree.executions) == 1
    execution = _OneLotMarketEntryOnBarThree.executions[0]
    raw_next_open = 19020.0
    expected_slipped_price = raw_next_open * (1.0 + 3.0 / 10000.0)
    assert execution["price"] == pytest.approx(expected_slipped_price)
    assert execution["price"] != raw_next_open
    assert execution["commission"] == pytest.approx(3.01, abs=MONEY_TOLERANCE_RMB)
