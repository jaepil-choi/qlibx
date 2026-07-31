"""Carry indicator registry — the curve/multi-contract kind.

The 5 carry calculators take a forward-curve ``curve_snapshot`` (and, for the
rolling three, a trailing history series) — NOT a single-contract ``df`` — so
they are deliberately absent from the per-contract ta-lib ``INDICATOR_MAPPING``.
This registry is their catalog-ingest source: it exposes their canonical names +
the *tunable* params (the curve_snapshot / history args are data inputs, not
tunables, so they are not listed here).

Hydrated into ``echolon.indicators.catalog`` via ``_ingest_curve`` with
``kind="curve_carry"`` and ``compute_source="echolon_curve_stage"`` — carry is
computed engine-side by the indicator processor's curve stage.

Design: docs (qorka) ``2026-06-08-carry-indicator-catalog-and-engine-wiring.md``.
"""
from __future__ import annotations

from .utils import (
    DEFAULT_CHANGE_LAG,
    DEFAULT_SLOPE_N,
    DEFAULT_VOL_WINDOW,
    DEFAULT_Z_WINDOW,
)

# name -> {"function": <module fn name>, "params": [{name, default, type}, ...]}
# params list the TUNABLE args only (curve_snapshot / *_history / *_series are
# data inputs, excluded — mirrors how the ta-lib catalog excludes ``df``).
CURVE_INDICATOR_MAP: dict[str, dict] = {
    "carry_front_back": {
        "function": "carry_front_back",
        "params": [],  # threshold is fixed at 0 by economic convention — not tunable
    },
    "curve_slope_near": {
        "function": "curve_slope_near",
        "params": [{"name": "n", "default": DEFAULT_SLOPE_N, "type": "int"}],
    },
    "risk_adj_carry": {
        "function": "risk_adj_carry",
        "params": [{"name": "window", "default": DEFAULT_VOL_WINDOW, "type": "int"}],
    },
    "carry_z_3m": {
        "function": "carry_z_3m",
        "params": [{"name": "window", "default": DEFAULT_Z_WINDOW, "type": "int"}],
    },
    "carry_change_20d": {
        "function": "carry_change_20d",
        "params": [{"name": "lag", "default": DEFAULT_CHANGE_LAG, "type": "int"}],
    },
}

__all__ = ["CURVE_INDICATOR_MAP"]
