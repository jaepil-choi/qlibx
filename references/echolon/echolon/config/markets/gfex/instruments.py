"""GFEX (Guangzhou Futures Exchange) instrument specifications.

Panel-v5 expansion (FV3 WP-X1b). This module is the canonical declarative spec
source for GFEX contracts, mirroring ``echolon/config/markets/shfe/instruments``.

Authoritative fields:
    ``multiplier`` (交易单位) and ``tick_size`` (最小变动单位) are exchange
    contract specifications, verified 2026-07-19 against akshare
    ``futures_contract_info_gfex`` and cross-checked against
    ``futures_fees_info`` (合约乘数/最小跳动).

Commission fields:
    ``commission`` and ``close_today_commission`` are the exchange-standard rate
    (万分之1 开仓/平昨, free 平今), reconciled 2026-07-20 to the ratified
    full-panel commission authority; the akshare +0.000001 offset is excluded.

Non-authoritative fields:
    ``margin_rate`` is a broker-observed snapshot (akshare ``futures_fees_info``,
    updated 2026-07-18) and changes over time. Session windows are NOT authored
    here (GFEX has no night session, and no intraday session/phase model is
    consumed by the panel-v5 pipeline); ``sessions`` is left empty and
    ``has_night_session`` unset by design. Consumers needing session data must
    not rely on this module yet.
"""

from typing import Dict

from ..core.types import InstrumentSpec


INSTRUMENTS: Dict[str, InstrumentSpec] = {
    'si': InstrumentSpec(
        code='si',
        name='industrial_silicon',
        market='GFEX',
        multiplier=5.0,           # 5吨/手 (5 tons per lot) — verified
        tick_size=5.0,            # 5元/吨 — verified
        margin_rate=0.10,         # akshare futures_fees_info snapshot 2026-07-18
        commission=0.0001,        # 万分之1 (开仓/平昨); exchange-standard, akshare +0.000001 offset excluded (2026-07-20)
        commission_type='percentage',
        close_today_commission=0.0,  # 平今 free
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=False,
        sessions=[],
    ),
}


def get_instrument(code: str) -> InstrumentSpec:
    """Get instrument specification by code."""
    return INSTRUMENTS[code.lower()]


def list_instruments() -> list:
    """Get list of all instrument codes."""
    return list(INSTRUMENTS.keys())
