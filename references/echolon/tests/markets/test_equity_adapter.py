from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from echolon.data.loaders.calendar_loader import is_night_market_open
from echolon.engine.factory import EngineFactory
from echolon.markets.equity import EquityAdapter


@pytest.fixture
def calendar_path(tmp_path: Path) -> Path:
    path = tmp_path / "trading_calendar.csv"
    pd.DataFrame({"date": ["2023-01-03", "2023-01-04"]}).to_csv(path, index=False)
    return path


def test_equity_adapter_requires_injected_calendar():
    with pytest.raises(ValueError, match="calendar"):
        EquityAdapter(symbol="600000")


def test_equity_adapter_sessions_calendar_and_non_expiry(calendar_path: Path):
    adapter = EquityAdapter(symbol="600000", trading_calendar_path=calendar_path)

    assert adapter.market_code == "EQUITY"
    assert adapter.market_name == "A-Share Equity"
    assert adapter.timezone == "Asia/Shanghai"
    assert [(s.start, s.end) for s in adapter.trading_sessions] == [
        (dt.time(9, 30), dt.time(11, 30)),
        (dt.time(13, 0), dt.time(15, 0)),
    ]
    assert adapter.supports_overnight_positions
    assert not adapter.has_contract_expiry
    assert adapter.get_main_contract(dt.date(2023, 1, 3)) == "600000"
    assert adapter.get_contract_expiry_date("600000") is None
    assert not adapter.should_rollover("600000", dt.date(2023, 1, 3), 100)
    assert adapter.get_rollover_target("600000", dt.date(2023, 1, 3)) is None
    assert adapter.is_trading_day(dt.date(2023, 1, 3))
    assert not adapter.is_trading_day(dt.date(2023, 1, 2))
    assert adapter.get_next_trading_day(dt.date(2023, 1, 3)) == dt.date(2023, 1, 4)
    assert adapter.get_previous_trading_day(dt.date(2023, 1, 4)) == dt.date(2023, 1, 3)
    with pytest.raises(KeyError, match="next trading day"):
        adapter.get_next_trading_day(dt.date(2023, 1, 4))


def test_equity_adapter_costs_rounding_and_factory(calendar_path: Path):
    adapter = EquityAdapter(symbol="600000", trading_calendar_path=calendar_path)
    assert adapter.round_size(249, "600000") == 200
    assert adapter.round_size(251, "600000") == 300
    assert adapter.calculate_commission("600000", 200, 10.0, side="SELL") == pytest.approx(6.02)

    ctx = SimpleNamespace(market_code="EQUITY", instrument_code="600000")
    made = EngineFactory.create_market_adapter(ctx, calendar_path=str(calendar_path))
    assert isinstance(made, EquityAdapter)


def test_equity_is_never_night_open_even_when_calendar_data_is_missing(tmp_path: Path):
    assert not is_night_market_open(
        "EQUITY", "600000", dt.datetime(2023, 1, 3), market_data_dir=tmp_path
    )
