"""
SHFE Market Configuration Aggregator.

This module aggregates all SHFE-specific configurations and registers
the market with the global MarketRegistry.

Import this module to register SHFE with the market system.
"""

from ..core.types import MarketConfig
from ..core.registry import MarketRegistry

from ..shfe.sessions import SESSIONS, ALL_SESSIONS
from ..shfe.phases import PHASES
from ..shfe.instruments import INSTRUMENTS


# =============================================================================
# SHFE Market Configuration
# =============================================================================

CONFIG = MarketConfig(
 code='SHFE',
 name='Shanghai Futures Exchange',
 full_name='Shanghai Futures Exchange',
 timezone='Asia/Shanghai',
 currency='CNY',
 chinese_name='上期所',
 xuntou_code='SF',
 supports_overnight=True,
 has_contract_expiry=True,
 is_24h=False,
 instruments=INSTRUMENTS,
 sessions=SESSIONS,
 phases=PHASES,
 # Trading calendar settings
 trading_days_per_week=5.0,
 trading_days_per_year=242, # ~242 trading days for Chinese futures
 min_position_unit=1.0,
)


# =============================================================================
# Auto-register on import
# =============================================================================

MarketRegistry.register(CONFIG)


# =============================================================================
# Module-level exports for convenience
# =============================================================================

# Re-export commonly used items
from ..shfe.sessions import (
 NIGHT,
 DAY1,
 DAY2,
 AFTERNOON,
 ALL_SESSIONS,
 DAY_SESSIONS,
 NIGHT_SESSIONS,
)

from ..shfe.phases import (
 PHASES,
 TRADING_PHASES,
 PHASE_ENCODING,
 PHASE_DECODING,
 encode_phase,
 decode_phase,
 get_phase_for_time,
 is_trading_time,
)

from ..shfe.instruments import (
 INSTRUMENTS,
 get_instrument,
 list_instruments,
)

from ..shfe.constants import (
 TOTAL_TRADING_MINUTES,
 DAY_TRADING_MINUTES,
 NIGHT_TRADING_MINUTES,
 BARS_PER_DAY,
 BARS_PER_DAY_NO_NIGHT,
 get_bars_per_day,
 get_trading_minutes,
)
