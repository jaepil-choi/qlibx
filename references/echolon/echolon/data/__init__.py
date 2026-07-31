"""Echolon data pipeline — public API.

Import from here rather than from sub-modules for a stable, discoverable surface.

Quick reference
---------------
Entry points::

 from echolon.data import run_data_pipeline, run_live_data_update

Loaders::

 from echolon.data import load_ohlcv, load_trading_calendar, load_session_availability
 from echolon.data import load_backtest_data, load_indicator_metadata

Extractors::

 from echolon.data import SHFEFileDayExtractor, BinancePerpetualExtractor

Transformers::

 from echolon.data import OHLCVStandardizer, SessionFilter
"""

# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
from echolon.data.backtest_data import run_data_pipeline
from echolon.data.live_data import run_live_data_update

# Alias for the concise public name used in the top-level package.
run_pipeline = run_data_pipeline

# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------
from echolon.data.extractors.base import BaseExtractor, XtdataClient
from echolon.data.extractors.shfe.file_day_extractor import SHFEFileDayExtractor
from echolon.data.extractors.shfe.api_day_extractor import SHFEApiDayExtractor
from echolon.data.extractors.shfe.api_minute_extractor import SHFEApiMinuteExtractor
from echolon.data.extractors.binance.perpetual_extractor import BinancePerpetualExtractor

# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
from echolon.data.loaders.ohlcv_loader import load_ohlcv, load_contract_ohlcv
from echolon.data.loaders.calendar_loader import (
 load_trading_calendar,
 get_trading_dates,
 is_trading_day,
)
from echolon.data.loaders.session_availability_loader import (
 SessionAvailabilityLoader,
 get_session_availability_loader,
)
from echolon.data.loaders.backtest_data_loader import (
 load_backtest_data,
 load_indicator_metadata,
 load_best_params,
)
from echolon.data.loaders.contract_loader import (
 ContractIndicatorManager,
 get_main_contract,
)

# ---------------------------------------------------------------------------
# Transformers
# ---------------------------------------------------------------------------
from echolon.data.transformers.ohlcv_standardizer import OHLCVStandardizer
from echolon.data.transformers.session_filter import SessionFilter
from echolon.data.transformers.ohlcv_resampler import OHLCVResampler
from echolon.data.transformers.contract_splitter import ContractSplitter
from echolon.data.transformers.calendar_generator import CalendarGenerator
from echolon.data.transformers.session_availability_builder import (
 SessionDayInfo,
 build_expected_bars,
)

__all__ = [
 # Entry points
 "run_data_pipeline",
 "run_live_data_update",
 "run_pipeline",
 # Extractors
 "BaseExtractor",
 "XtdataClient",
 "SHFEFileDayExtractor",
 "SHFEApiDayExtractor",
 "SHFEApiMinuteExtractor",
 "BinancePerpetualExtractor",
 # Loaders
 "load_ohlcv",
 "load_contract_ohlcv",
 "load_trading_calendar",
 "get_trading_dates",
 "is_trading_day",
 "SessionAvailabilityLoader",
 "get_session_availability_loader",
 "load_backtest_data",
 "load_indicator_metadata",
 "load_best_params",
 "ContractIndicatorManager",
 "get_main_contract",
 # Transformers
 "OHLCVStandardizer",
 "SessionFilter",
 "OHLCVResampler",
 "ContractSplitter",
 "CalendarGenerator",
 "SessionDayInfo",
 "build_expected_bars",
]
