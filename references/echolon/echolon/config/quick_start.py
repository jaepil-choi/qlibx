"""quick_start() — convenience helper for common cases."""

import os
from pathlib import Path

from echolon.config.backtest_config import BacktestConfig
from echolon.config.markets.core.context import TradingContext
from echolon.config.optuna_config import OptunaConfig


def quick_start(
 market: str,
 instrument: str,
 start_date: str,
 end_date: str,
 frequency: str = "interday",
 bar_size: str = "1d",
) -> tuple[TradingContext, BacktestConfig, OptunaConfig]:
 """Build default configs for common cases."""
 ctx = TradingContext.from_market(
 market=market,
 instrument=instrument,
 frequency=frequency,
 bar_size=bar_size,
 )

 workspace = Path(os.getenv("ECHOLON_WORKSPACE_DIR", "workspace"))
 data = Path(os.getenv("ECHOLON_DATA_DIR", "data"))

 bt = BacktestConfig(
 start_date=start_date,
 end_date=end_date,
 strategy_dir=workspace / "code",
 market_data_dir=data / "market",
 indicator_dir=data / "indicators",
 results_dir=workspace / "results",
 )

 opt = OptunaConfig()

 return ctx, bt, opt
