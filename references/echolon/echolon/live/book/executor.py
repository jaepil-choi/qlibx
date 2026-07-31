"""Translate target lots into order-router intents.

The executor owns exactly one job: the arithmetic from (held lots, target
lots) to intent-labelled orders. Reversals decompose into an exit followed
by an entry, and same-direction reductions emit partial exits, so live
records preserve intent-specific costs and close-today (平今) treatment.
"""
from __future__ import annotations

from collections.abc import Mapping

from echolon.portfolio import TargetBook

from .models import DiffOrder, OrderRouterLike


class TargetExecutor:
    """Submit only the lot deltas required to move the held book to target."""

    def __init__(
        self,
        *,
        router: OrderRouterLike,
        book_id: str,
        symbol_map: Mapping[str, str],
    ) -> None:
        self.router = router
        self.book_id = book_id
        self.symbol_map = {key.lower(): value for key, value in symbol_map.items()}

    def plan(
        self,
        target: TargetBook,
        *,
        current_lots: Mapping[str, int],
    ) -> list[DiffOrder]:
        """Compute the order plan without submitting anything."""
        current = {key.lower(): _int_lots(value, "current") for key, value in current_lots.items()}
        targets = {key.lower(): _int_lots(value, "target") for key, value in target.targets.items()}
        instruments = sorted(set(current) | set(targets))
        orders: list[DiffOrder] = []
        for instrument in instruments:
            before = current.get(instrument, 0)
            after = targets.get(instrument, 0)
            if before == after:
                continue
            orders.extend(self._orders_for_diff(instrument, before, after))
        return orders

    def execute(
        self,
        target: TargetBook,
        *,
        current_lots: Mapping[str, int],
    ) -> list[DiffOrder]:
        """Plan and submit the diff orders through the router.

        Router-side refusals (e.g. a tripped circuit) propagate: partial
        submission is reported by the raised error, never papered over.
        """
        orders = self.plan(target, current_lots=current_lots)
        for order in orders:
            self.router.submit_order(
                intent=order.intent,
                symbol=order.symbol,
                volume=order.volume,
                slot_id=self.book_id,
            )
        return orders

    def _orders_for_diff(self, instrument: str, before: int, after: int) -> list[DiffOrder]:
        symbol = self._symbol_for(instrument)
        orders: list[DiffOrder] = []
        sign_flip = (before > 0 > after) or (before < 0 < after)
        if sign_flip:
            exit_intent = "EXIT_LONG" if before > 0 else "EXIT_SHORT"
            entry_intent = "ENTRY_LONG" if after > 0 else "ENTRY_SHORT"
            orders.append(DiffOrder(instrument, symbol, exit_intent, abs(before)))
            orders.append(DiffOrder(instrument, symbol, entry_intent, abs(after)))
            return orders
        delta = after - before
        if abs(after) > abs(before):
            # Moving away from flat (includes opening from flat).
            intent = "ENTRY_LONG" if after > 0 else "ENTRY_SHORT"
        else:
            # Moving toward flat: partial or full exit of the held side.
            intent = "EXIT_LONG" if before > 0 else "EXIT_SHORT"
        orders.append(DiffOrder(instrument, symbol, intent, abs(delta)))
        return orders

    def _symbol_for(self, instrument: str) -> str:
        try:
            return self.symbol_map[instrument]
        except KeyError as exc:
            raise KeyError(f"missing live symbol for instrument {instrument}") from exc


def _int_lots(value: float | int, kind: str) -> int:
    lots = float(value)
    if not lots.is_integer():
        raise ValueError(
            f"{kind} lots must be integers for live execution, got {value!r} — "
            "research-sized (fractional) targets are not deployable"
        )
    return int(lots)
