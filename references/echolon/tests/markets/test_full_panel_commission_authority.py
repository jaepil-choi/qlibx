"""Falsifier: echolon canonical commission == the ratified full-panel authority (v3).

The round-3 full-panel commission audit (ratified 2026-07-20) corrected the
exchange-standard commission / commission_type / close-today (平今) legs for the panel
products. The runtime spec sources must match the authority (instrument-consistency law).
akshare's ``futures_fees_info`` +0.01 元/手 (or +0.000001 rate) broker-negotiated offset
is deliberately excluded.

Echolon's ``config/markets/*/instruments.py`` registries are the DECLARATIVE spec source
consumed by the market adapters; they cover 20 of the 42 panel products (the other 22 are
sourced solely from the panel meta, which the qorka panel-meta falsifier holds). This test
holds the 20 present products to the authority.

close-today convention: the authority records the TRUE 平今 rate (free=0.0, flat==commission,
double=2x). A spec may carry ``close_today_commission=None`` for flat (calculate_commission
falls back to ``commission``); free/double MUST be explicit. The falsifier therefore compares
the EFFECTIVE close-today: ``close_today_commission if not None else commission``.

Layers:
  1. always-on value pin (no external dependency);
  2. cross-artifact consistency vs the ratified authority JSON (skips if store unavailable);
  3. single-source consistency: no panel product is defined in more than one registry.
"""

from __future__ import annotations

import json
from pathlib import Path

from echolon.config.markets.shfe.instruments import INSTRUMENTS as SHFE
from echolon.config.markets.czce.instruments import INSTRUMENTS as CZCE
from echolon.config.markets.gfex.instruments import INSTRUMENTS as GFEX
from echolon.config.markets.dce.instruments import INSTRUMENTS as DCE

_REGISTRIES = {"SHFE": SHFE, "CZCE": CZCE, "GFEX": GFEX, "DCE": DCE}

# Ratified exchange-standard schedule (元/手 for per_contract; fraction for percentage) for
# the 20 panel products present in echolon canonical. Tuple = (commission, commission_type,
# effective_close_today_true_rate). free=0.0, flat==commission, double=2x.
RATIFIED = {
    # SHFE (12)
    "al": (3.0, "per_contract", 3.0),
    "cu": (0.00005, "percentage", 0.0001),   # 平今 doubles
    "zn": (3.0, "per_contract", 0.0),         # 平今 free
    "ni": (3.0, "per_contract", 3.0),         # clean match
    "ag": (0.00001, "percentage", 0.00001),   # level fix; akshare 5x conflict disclosed
    "rb": (0.0001, "percentage", 0.0001),
    "hc": (0.0001, "percentage", 0.0001),
    "bu": (0.00005, "percentage", 0.0),       # level + 平今 free
    "ru": (3.0, "per_contract", 0.0),         # TYPE fix + 平今 free
    "ao": (0.0001, "percentage", 0.0001),     # broker-offset normalize
    "ss": (2.0, "per_contract", 0.0),         # level + 平今 free
    "pb": (0.00004, "percentage", 0.0),       # 平今 free
    # CZCE (3)
    "ap": (5.0, "per_contract", 10.0),        # 平今 doubles
    "cj": (3.0, "per_contract", 3.0),
    "pk": (2.0, "per_contract", 2.0),         # 郑商函〔2026〕91号 eff. 2026-06-24
    # GFEX (1)
    "si": (0.0001, "percentage", 0.0),        # 平今 free
    # DCE (4) — v2, unchanged
    "eb": (1.0, "per_contract", 1.0),
    "a": (2.0, "per_contract", 2.0),
    "b": (1.0, "per_contract", 1.0),
    "cs": (1.5, "per_contract", 1.5),
}


def _lookup(code: str):
    for reg in _REGISTRIES.values():
        if code in reg:
            return reg[code]
    raise KeyError(code)


def _effective_close_today(spec) -> float:
    return (
        spec.close_today_commission
        if spec.close_today_commission is not None
        else spec.commission
    )


def test_echolon_present_products_match_ratified_schedule() -> None:
    for code, (commission, ctype, eff_ct) in RATIFIED.items():
        spec = _lookup(code)
        assert spec.commission == commission, (code, spec.commission, commission)
        assert spec.commission_type == ctype, (code, spec.commission_type, ctype)
        assert _effective_close_today(spec) == eff_ct, (
            code,
            _effective_close_today(spec),
            eff_ct,
        )


def test_present_products_match_v3_authority_artifact(
    commission_authority_v3: Path,
) -> None:
    """Echolon canonical == the v3 authority ``records`` for every present panel product."""
    records = json.loads(commission_authority_v3.read_text())["records"]
    for code in RATIFIED:
        rec = records[code]
        spec = _lookup(code)
        assert spec.commission == rec["commission"], code
        assert spec.commission_type == rec["commission_type"], code
        assert _effective_close_today(spec) == rec["close_today_commission"], code


def test_no_panel_product_defined_in_multiple_registries() -> None:
    """Single-source consistency: each panel product has exactly one echolon spec location,
    so no divergent duplicate can exist (instrument-consistency law)."""
    seen: dict[str, str] = {}
    for exch, reg in _REGISTRIES.items():
        for code in reg:
            if code in RATIFIED:
                assert code not in seen, (code, seen.get(code), exch)
                seen[code] = exch
    assert set(seen) == set(RATIFIED)
