"""
SHFE Instrument Specifications.

Contains complete specifications for all tradable instruments on
Shanghai Futures Exchange (SHFE).

Each instrument includes:
- Contract specifications (multiplier, tick size, margin)
- Commission structure
- Session information (night session availability)
"""

from typing import Dict

from ..core.types import InstrumentSpec
from .sessions import ALL_SESSIONS


INSTRUMENTS: Dict[str, InstrumentSpec] = {
    # =========================================================================
    # Base Metals
    # =========================================================================
    'al': InstrumentSpec(
        code='al',
        name='aluminum',
        market='SHFE',
        multiplier=5.0,           # 5吨/手 (5 tons per lot)
        tick_size=5.0,            # 5元/吨 (5 CNY minimum price move per ton)
        margin_rate=0.09,         # 合约价值的5% (5% of contract value)
        commission=3.0,           # 元/手 (开仓/平昨); exchange-standard, akshare +0.01 broker offset excluded (2026-07-20)
        commission_type='per_contract',
        close_today_commission=3.0,  # 平今 flat (= 开仓)
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),
    'cu': InstrumentSpec(
        code='cu',
        name='copper',
        market='SHFE',
        multiplier=5.0,           # 5 tons per contract
        tick_size=10.0,           # 10 CNY minimum price move
        margin_rate=0.09,         # 10% margin
        commission=0.00005,       # 万分之0.5 of trade value (开仓/平昨); exchange-standard (2026-07-20)
        commission_type='percentage',
        close_today_commission=0.0001,  # 平今 doubles the base (万分之1)
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),
    'zn': InstrumentSpec(
        code='zn',
        name='zinc',
        market='SHFE',
        multiplier=5.0,
        tick_size=5.0,
        margin_rate=0.10,
        commission=3.0,           # 元/手 (开仓/平昨); exchange-standard (2026-07-20)
        commission_type='per_contract',
        close_today_commission=0.0,  # 平今 free
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),
    'pb': InstrumentSpec(
        code='pb',
        name='lead',
        market='SHFE',
        multiplier=5.0,
        tick_size=5.0,
        margin_rate=0.10,
        commission=0.00004,       # 万分之0.4 of trade value (开仓/平昨); exchange-standard (2026-07-20)
        commission_type='percentage',
        close_today_commission=0.0,  # 平今 free
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),
    'ni': InstrumentSpec(
        code='ni',
        name='nickel',
        market='SHFE',
        multiplier=1.0,           # 1 ton per contract
        tick_size=10.0,
        margin_rate=0.14,         # Higher margin for nickel
        commission=3.0,
        commission_type='per_contract',
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),
    'sn': InstrumentSpec(
        code='sn',
        name='tin',
        market='SHFE',
        multiplier=1.0,
        tick_size=10.0,
        margin_rate=0.12,
        commission=3.0,
        commission_type='per_contract',
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),
    'ao': InstrumentSpec(
        code='ao',
        name='alumina',
        market='SHFE',
        # Contract spec (multiplier 20 吨/手, tick 1 元/吨) verified against
        # akshare futures_fees_info (合约乘数/最小跳动) 2026-07-19; panel-v5 add.
        multiplier=20.0,          # 20吨/手 (20 tons per lot)
        tick_size=1.0,            # 1元/吨
        # margin/commission are broker-observed snapshots (akshare
        # futures_fees_info, updated 2026-07-18) and vary over time.
        margin_rate=0.11,
        commission=0.0001,        # 万分之1 flat (开仓/平昨/平今); exchange-standard, akshare +0.000001 offset excluded (2026-07-20)
        commission_type='percentage',
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),

    # =========================================================================
    # Precious Metals
    # =========================================================================
    'au': InstrumentSpec(
        code='au',
        name='gold',
        market='SHFE',
        multiplier=1000.0,        # 1000 grams per contract
        tick_size=0.02,
        margin_rate=0.10,
        commission=10.0,
        commission_type='per_contract',
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),
    'ag': InstrumentSpec(
        code='ag',
        name='silver',
        market='SHFE',
        multiplier=15.0,          # 15 kg per contract
        tick_size=1.0,
        margin_rate=0.11,
        commission=0.00001,       # 万分之0.1 flat (开仓/平昨/平今); 3-portal majority (akshare implies 5x, conflict disclosed in authority v3) (2026-07-20)
        commission_type='percentage',
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),

    # =========================================================================
    # Ferrous Metals / Steel
    # =========================================================================
    'rb': InstrumentSpec(
        code='rb',
        name='rebar',
        market='SHFE',
        multiplier=10.0,          # 10 tons per contract
        tick_size=1.0,
        margin_rate=0.07,
        commission=0.0001,        # 万分之1 flat (开仓/平昨/平今); exchange-standard (2026-07-20)
        commission_type='percentage',
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),
    'hc': InstrumentSpec(
        code='hc',
        name='hot_rolled_coil',
        market='SHFE',
        multiplier=10.0,
        tick_size=1.0,
        margin_rate=0.09,
        commission=0.0001,        # 万分之1 flat (开仓/平昨/平今); exchange-standard (2026-07-20)
        commission_type='percentage',
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),
    'ss': InstrumentSpec(
        code='ss',
        name='stainless_steel',
        market='SHFE',
        multiplier=5.0,
        tick_size=5.0,
        margin_rate=0.10,
        commission=2.0,           # 元/手 (开仓/平昨); exchange-standard, level corrected (2026-07-20)
        commission_type='per_contract',
        close_today_commission=0.0,  # 平今 free
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),

    # =========================================================================
    # Energy / Chemicals
    # =========================================================================
    'bu': InstrumentSpec(
        code='bu',
        name='bitumen',
        market='SHFE',
        multiplier=10.0,
        tick_size=2.0,
        margin_rate=0.10,
        commission=0.00005,       # 万分之0.5 (开仓/平昨); exchange-standard, level corrected (2026-07-20)
        commission_type='percentage',
        close_today_commission=0.0,  # 平今 free
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),
    'ru': InstrumentSpec(
        code='ru',
        name='rubber',
        market='SHFE',
        multiplier=10.0,
        tick_size=5.0,
        margin_rate=0.09,
        commission=3.0,           # 元/手 flat (开仓/平昨); TYPE corrected percentage->per_contract; exchange-standard (2026-07-20)
        commission_type='per_contract',
        close_today_commission=0.0,  # 平今 free
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),
    'sp': InstrumentSpec(
        code='sp',
        name='pulp',
        market='SHFE',
        multiplier=10.0,
        tick_size=2.0,
        margin_rate=0.10,
        commission=0.00005,
        commission_type='percentage',
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=True,
        sessions=ALL_SESSIONS,
    ),
}


def get_instrument(code: str) -> InstrumentSpec:
    """Get instrument specification by code."""
    return INSTRUMENTS[code.lower()]


def list_instruments() -> list:
    """Get list of all instrument codes."""
    return list(INSTRUMENTS.keys())


def get_by_category(category: str) -> Dict[str, InstrumentSpec]:
    """
    Get instruments by category.

    Categories: 'base_metals', 'precious_metals', 'ferrous', 'energy'
    """
    categories = {
        'base_metals': ['al', 'cu', 'zn', 'pb', 'ni', 'sn', 'ao'],
        'precious_metals': ['au', 'ag'],
        'ferrous': ['rb', 'hc', 'ss'],
        'energy': ['bu', 'ru', 'sp'],
    }
    codes = categories.get(category, [])
    return {c: INSTRUMENTS[c] for c in codes if c in INSTRUMENTS}


# Set of instrument codes that have night session
NIGHT_SESSION_PRODUCTS = {
    code for code, spec in INSTRUMENTS.items()
    if spec.has_night_session
}

# Derived mappings from INSTRUMENTS (no duplication)
NAME_TO_CODE = {spec.name: spec.code for spec in INSTRUMENTS.values()}
CODE_TO_NAME = {spec.code: spec.name for spec in INSTRUMENTS.values()}


def get_code_from_name(name: str) -> str:
    """Get instrument code from full name (e.g., 'aluminum' -> 'al')."""
    return NAME_TO_CODE.get(name.lower())


def get_name_from_code(code: str) -> str:
    """Get instrument name from code (e.g., 'al' -> 'aluminum')."""
    return CODE_TO_NAME.get(code.lower())


def get_instrument_by_name(name: str) -> InstrumentSpec:
    """Get instrument specification by full name."""
    code = NAME_TO_CODE.get(name.lower())
    if code:
        return INSTRUMENTS[code]
    return None


def get_instrument_flexible(identifier: str) -> InstrumentSpec:
    """
    Get instrument by either code or name.

    Args:
        identifier: Either code ('al') or name ('aluminum')

    Returns:
        InstrumentSpec or None
    """
    identifier = identifier.lower()
    # Try as code first
    if identifier in INSTRUMENTS:
        return INSTRUMENTS[identifier]
    # Try as name
    code = NAME_TO_CODE.get(identifier)
    if code:
        return INSTRUMENTS[code]
    return None
