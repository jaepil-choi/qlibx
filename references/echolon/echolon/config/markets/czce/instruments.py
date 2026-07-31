"""CZCE (Zhengzhou Commodity Exchange) instrument specifications.

Panel-v5 expansion (FV3 WP-X1b). Canonical declarative spec source for the CZCE
products added this round, mirroring ``echolon/config/markets/shfe/instruments``.

Authoritative fields:
    ``multiplier`` (交易单位) and ``tick_size`` (最小变动价位) are exchange
    contract specifications, verified 2026-07-19 against akshare
    ``futures_contract_info_czce`` and cross-checked against
    ``futures_fees_info`` (合约乘数/最小跳动).

Commission fields:
    ``commission`` and ``close_today_commission`` are the exchange-standard
    per-lot rate (元/手), reconciled 2026-07-20 to the ratified full-panel
    commission authority. The akshare ``futures_fees_info`` +0.01 元/手
    broker-negotiated offset is excluded. pk carries the 郑商函〔2026〕91号 rate
    effective 2026-06-24.

Non-authoritative fields:
    ``margin_rate`` is a broker-observed snapshot (akshare ``futures_fees_info``,
    updated 2026-07-18) and changes over time. Session windows are NOT authored
    here (no intraday session/phase model is consumed by the panel-v5 pipeline);
    ``sessions`` is left empty and ``has_night_session`` unset by design.

NOTE: CZCE contract identifiers repeat every decade (three-digit codes). These
specs are product-level (multiplier/tick), which do not carry that ambiguity;
any contract-level (episode-keyed) logic lives in ``echolon.markets.expiry``.
"""

from typing import Dict

from ..core.types import InstrumentSpec


INSTRUMENTS: Dict[str, InstrumentSpec] = {
    'ap': InstrumentSpec(
        code='ap',
        name='apple',
        market='CZCE',
        multiplier=10.0,          # 10吨/手 — verified
        tick_size=1.0,            # 1元/吨 — verified
        margin_rate=0.09,         # akshare futures_fees_info snapshot 2026-07-18
        commission=5.0,           # 元/手 (开仓/平昨); exchange-standard, akshare +0.01 offset excluded (2026-07-20)
        commission_type='per_contract',
        close_today_commission=10.0,  # 平今 doubles the base
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=False,
        sessions=[],
    ),
    'cj': InstrumentSpec(
        code='cj',
        name='jujube',
        market='CZCE',
        multiplier=5.0,           # 5吨/手 — verified
        tick_size=5.0,            # 5元/吨 — verified
        margin_rate=0.08,         # akshare futures_fees_info snapshot 2026-07-18
        commission=3.0,           # 元/手 flat (开仓/平昨/平今); exchange-standard, akshare +0.01 offset excluded (2026-07-20)
        commission_type='per_contract',
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=False,
        sessions=[],
    ),
    'pk': InstrumentSpec(
        code='pk',
        name='peanut',
        market='CZCE',
        multiplier=5.0,           # 5吨/手 — verified
        tick_size=2.0,            # 2元/吨 — verified
        margin_rate=0.07,         # akshare futures_fees_info snapshot 2026-07-18
        commission=2.0,           # 元/手 flat (开仓/平昨/平今); exchange-standard, akshare +0.01 offset excluded (2026-07-20) — 郑商函〔2026〕91号 eff. 2026-06-24
        commission_type='per_contract',
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
