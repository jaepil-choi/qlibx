"""
Crypto Market Configuration Aggregator.

Registers the crypto perpetuals market with the global MarketRegistry.
This provides a generic crypto configuration that can be used as a base.

For exchange-specific configurations (Binance, OKX), create submodules
that extend or override these defaults.
"""

from ..core.types import MarketConfig
from ..core.registry import MarketRegistry

from ..crypto.perpetuals import (
 SESSIONS,
 PHASES,
 PERPETUALS,
 ALL_SESSIONS,
 TOTAL_TRADING_MINUTES,
 BARS_PER_DAY,
 get_bars_per_day,
)


# =============================================================================
# Crypto Market Configuration
# =============================================================================

CONFIG = MarketConfig(
 code='CRYPTO',
 name='Crypto Perpetuals',
 full_name='Cryptocurrency Perpetual Futures',
 timezone='UTC',
 currency='USDT',
 chinese_name=None,
 xuntou_code=None,
 supports_overnight=True, # Always open
 has_contract_expiry=False, # Perpetual - no expiry
 is_24h=True,
 trading_days_per_week=7.0, # 24/7 trading
 trading_days_per_year=365, # No market holidays
 min_position_unit=0.001, # Fractional positions allowed
 instruments=PERPETUALS,
 sessions=SESSIONS,
 phases=PHASES,
)


# =============================================================================
# Auto-register on import
# =============================================================================

MarketRegistry.register(CONFIG)


# =============================================================================
# Module-level exports
# =============================================================================

# Re-export for convenience
from ..crypto.perpetuals import (
 CONTINUOUS_SESSION,
 SESSIONS,
 ALL_SESSIONS,
 PHASES,
 PERPETUALS,
 TOTAL_TRADING_MINUTES,
 BARS_PER_DAY,
 get_bars_per_day,
)
