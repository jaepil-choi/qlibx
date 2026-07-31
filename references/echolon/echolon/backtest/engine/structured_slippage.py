"""Structured slippage — per-intent + vol-regime cost model (cost-model v2).

Per qorka `docs/2_design/decisions_log.md` 2026-05-13 "Cost-model v2"
entry + Wave 1A plan T27b/c. The pre-existing scalar
``calibrated_slippage_bps`` (v1) is insufficient because real SHFE order
flow has materially different slippage by intent:

- **ENTRY**: discretionary opening trade; usually cross-market or near-mid;
  lower slippage.
- **EXIT**: discretionary closing trade; same flow characteristics as
  ENTRY for most strategies.
- **FORCED_EXIT**: stop-loss / contract-expiry / risk-cap exit — typically
  market-on-close or aggressive cross; materially higher slippage.

Vol-regime layer (T27c): during high-volatility periods (60-day rolling
vol percentile > threshold) the per-intent bps are multiplied by
``high_vol_slippage_multiplier``. The multiplier defaults to ``1.0`` so
the layer is a no-op until calibration tooling sets it.

This module ships:

- :class:`OrderIntent` — closed enum of the four intent classes.
- :func:`classify_order_intent` — pure-function classifier based on
  pre-fill position state + a forced-exit flag.
- :func:`compute_slippage_bps` — pure-function bps lookup with vol-regime
  multiplier application.
- :class:`StructuredSlippageBroker` — Backtrader broker subclass that
  installs the v2 path into `bt.cerebro`.

Per Gate 1A T27b/c (qorka 2026-05-14).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

import backtrader as bt


class OrderIntent(str, Enum):
    """Closed enum of order intent classes recognized by the v2 cost model."""

    ENTRY = "entry"
    EXIT = "exit"
    FORCED_EXIT = "forced_exit"
    # OTHER catches scale-in / scale-out trades that don't cleanly map to
    # the three primary intents. Treated as ENTRY-rate by default; callers
    # can override the per-intent dict to discriminate.
    OTHER = "other"


def classify_order_intent(
    order_size: float,
    position_before: float,
    is_forced_exit: bool = False,
) -> OrderIntent:
    """Classify an order's intent by inspecting position state pre-fill.

    Args:
        order_size: Signed order size (positive = buy, negative = sell).
        position_before: Signed position immediately before fill.
        is_forced_exit: True when the order originates from a forced-
            close pathway (stop-loss / contract-expiry / risk-cap).
            FORCED_EXIT only fires when the order is actually a closing
            trade (reducing |position|); a forced-close opening trade
            would be a calling-convention bug.

    Returns:
        :class:`OrderIntent` per the classification rule:

        - ``position_before == 0``: ENTRY (opening from flat)
        - ``order_size`` reduces ``|position_before|`` to zero
          (full close): EXIT or FORCED_EXIT (per ``is_forced_exit``)
        - ``order_size`` increases ``|position_before|`` (scale-in)
          or reduces but doesn't close (scale-out): OTHER

    The classifier doesn't consult bar-state — it's purely about the
    position-delta semantics. Callers route forced-close pathways via
    the ``is_forced_exit`` flag rather than embedding bar-context here.
    """
    if order_size == 0:
        # Defensive: a zero-size order shouldn't reach this function, but
        # if it does treat as OTHER rather than raising — the broker
        # downstream will reject the zero-size order anyway.
        return OrderIntent.OTHER

    if position_before == 0:
        # Opening from flat → ENTRY (forced-exit on an open is a bug;
        # don't claim that here.)
        return OrderIntent.ENTRY

    position_after = position_before + order_size
    # Full close: position_after exactly zero AND the order direction
    # opposes the existing position.
    if position_after == 0 and (
        (position_before > 0 and order_size < 0)
        or (position_before < 0 and order_size > 0)
    ):
        return OrderIntent.FORCED_EXIT if is_forced_exit else OrderIntent.EXIT

    # Scale-in (same direction) or scale-out (opposite direction but not
    # full close) — bucket as OTHER. Callers wanting per-bucket calibration
    # for these cases can extend the per-intent dict.
    return OrderIntent.OTHER


def compute_slippage_bps(
    intent: OrderIntent,
    by_intent: dict[str, float],
    vol_pct: Optional[float] = None,
    vol_threshold: float = 75.0,
    high_vol_multiplier: float = 1.0,
) -> float:
    """Resolve the bps for an order given its intent + current vol regime.

    Args:
        intent: The :class:`OrderIntent` to look up.
        by_intent: ``{intent_value: bps}`` dict from
            ``ContractSpec.calibrated_slippage_bps_by_intent``. Keys are
            ``OrderIntent`` string values.
        vol_pct: Current 60-day rolling vol percentile (0-100 scale).
            ``None`` → vol-regime check skipped, base bps returned.
        vol_threshold: Threshold above which the high-vol multiplier
            applies. Default 75 (top quartile).
        high_vol_multiplier: Multiplier applied to base bps when
            ``vol_pct > vol_threshold``. Default 1.0 = no-op.

    Returns:
        bps for this order. When ``intent`` is missing from
        ``by_intent``, falls back to the ENTRY bps; if ENTRY itself is
        absent, falls back to the mean of present values; if the dict
        is empty, returns 0 (the broker upstream guards against that).

    The fallback chain is deliberate: we want a usable value rather
    than KeyError when calibration data is sparse for some intents.
    Calibration tooling SHOULD populate all four classes, but if it
    doesn't, the broker stays functional.
    """
    if not by_intent:
        return 0.0

    base_bps = by_intent.get(intent.value)
    if base_bps is None:
        base_bps = by_intent.get(OrderIntent.ENTRY.value)
    if base_bps is None:
        base_bps = sum(by_intent.values()) / len(by_intent)

    if (
        vol_pct is not None
        and vol_pct > vol_threshold
        and high_vol_multiplier != 1.0
    ):
        base_bps = base_bps * high_vol_multiplier
    return float(base_bps)


class StructuredSlippageBroker(bt.brokers.BackBroker):
    """Backtrader broker subclass implementing the v2 cost model.

    Installed by ``backtrader_engine.py`` when
    ``ContractSpec.calibrated_slippage_bps_by_intent`` is set. Overrides
    the fill-price computation to apply per-intent + vol-regime bps
    rather than the inherited flat ``set_slippage_perc()`` scalar.

    Wire-up at engine setup:

        broker = StructuredSlippageBroker()
        broker.configure_v2(
            by_intent=spec.calibrated_slippage_bps_by_intent,
            high_vol_threshold=spec.high_vol_pct_threshold,
            high_vol_multiplier=spec.high_vol_slippage_multiplier,
        )
        cerebro.broker = broker

    The vol-regime check reads ``vol_pct`` from a strategy-supplied
    callback set via :meth:`set_vol_pct_provider`. If the provider
    isn't set, the vol-regime layer is skipped (high_vol_multiplier
    treated as 1.0).
    """

    params = ()

    def __init__(self):
        super().__init__()
        self._by_intent: dict[str, float] = {}
        self._high_vol_threshold: float = 75.0
        self._high_vol_multiplier: float = 1.0
        # Default vol-pct provider returns None → vol-regime skipped.
        # Strategy can override via set_vol_pct_provider(callable).
        self._vol_pct_provider = lambda: None
        # Forced-exit flag is set by the strategy via mark_next_order_forced()
        # then consumed (and reset) on the next order's classification.
        self._pending_forced_exit = False

    def configure_v2(
        self,
        by_intent: dict[str, float],
        high_vol_threshold: float = 75.0,
        high_vol_multiplier: float = 1.0,
    ) -> None:
        """Install the v2 calibration parameters on the broker.

        Call this immediately after constructing the broker, before
        any strategies are added to cerebro.
        """
        self._by_intent = dict(by_intent)
        self._high_vol_threshold = float(high_vol_threshold)
        self._high_vol_multiplier = float(high_vol_multiplier)

    def set_vol_pct_provider(self, provider) -> None:
        """Attach a callable that returns the current 60-day rolling vol
        percentile (0-100, or None when warmup-incomplete). The strategy
        usually wires this from its primary data feed."""
        self._vol_pct_provider = provider

    def mark_next_order_forced(self) -> None:
        """Strategy-side flag: the NEXT order placed is a forced exit
        (stop-loss / contract-expiry / risk-cap). Consumed once + reset
        on the next intent classification."""
        self._pending_forced_exit = True

    def _resolve_slippage_pct_for_order(self, order) -> float:
        """Compute the per-order slippage pct from the v2 cost model.

        Inspects position state pre-fill via ``self.getposition(order.data)``,
        classifies intent, looks up bps via :func:`compute_slippage_bps`,
        and converts to a percentage. The vol-pct provider is consulted
        once per order.
        """
        # Snapshot + reset forced-exit flag so a leftover marker can't
        # mis-classify a later non-forced trade.
        is_forced = self._pending_forced_exit
        self._pending_forced_exit = False

        position = self.getposition(order.data)
        position_before = position.size if position is not None else 0
        order_size = order.size if order.size is not None else 0
        intent = classify_order_intent(
            order_size=order_size,
            position_before=position_before,
            is_forced_exit=is_forced,
        )

        vol_pct = None
        try:
            vol_pct = self._vol_pct_provider()
        except Exception:
            # Provider failure shouldn't break the broker — skip vol-regime
            # check rather than crashing the backtest.
            vol_pct = None

        bps = compute_slippage_bps(
            intent=intent,
            by_intent=self._by_intent,
            vol_pct=vol_pct,
            vol_threshold=self._high_vol_threshold,
            high_vol_multiplier=self._high_vol_multiplier,
        )
        return bps / 10000.0  # bps → pct decimal

    def _slip_up(self, pmax, price, doslip=True, lim=False):
        """Override the inherited slip method to use per-order pct.

        Backtrader calls ``_slip_up`` when filling a buy order; the
        existing implementation uses ``self.p.slip_perc`` (a flat
        scalar). Here we route through ``_get_executor_slippage_pct``
        which looks up per-order intent."""
        if not doslip:
            return price
        # If the active order context is None (rare), fall back to the
        # parent's flat-scalar behavior.
        order = getattr(self, "_executor_active_order", None)
        slip_pct = (
            self._resolve_slippage_pct_for_order(order)
            if order is not None
            else self.p.slip_perc
        )
        price *= (1.0 + slip_pct)
        if pmax is not None:
            price = min(price, pmax)
        return price

    def _slip_down(self, pmin, price, doslip=True, lim=False):
        """Mirror of ``_slip_up`` for sell-side fills."""
        if not doslip:
            return price
        order = getattr(self, "_executor_active_order", None)
        slip_pct = (
            self._resolve_slippage_pct_for_order(order)
            if order is not None
            else self.p.slip_perc
        )
        price *= (1.0 - slip_pct)
        if pmin is not None:
            price = max(price, pmin)
        return price
