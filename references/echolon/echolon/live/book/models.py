"""Shared types for the bundle-era live book path.

Everything here is generic mechanism: no capital numbers, no instrument
universe, no account identity. The private platform (GoingMerry) injects
those at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from echolon.portfolio import RebalanceRecord, TargetBook


class OrderRouterLike(Protocol):
    """Minimal OrderRouter surface the book path depends on.

    Satisfied by the production ``echolon.live.platforms.miniqmt.OrderRouter``
    and by injectable test/paper transports, so no book test ever needs QMT.
    """

    def submit_order(
        self,
        *,
        intent: str,
        symbol: str,
        volume: int,
        slot_id: str,
        intended_price: float | None = None,
    ) -> Any: ...

    def trip_circuit(self, reason: str) -> None: ...


class QMTClientLike(Protocol):
    """Broker-query surface needed by book reconciliation (L1/L2)."""

    def query_stock_trades(self) -> list[Any]: ...

    def get_positions(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DiffOrder:
    """One order the executor derived from a target-vs-held lot diff."""

    instrument: str
    symbol: str
    intent: str
    volume: int


@dataclass(frozen=True)
class RiskCheckResult:
    halt: bool
    reason: str = ""
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BookRunResult:
    """Outcome of one book cycle: risk verdict, targets, and submitted orders."""

    halted: bool
    risk: RiskCheckResult
    target: TargetBook | None
    orders: list[DiffOrder]
    rebalance_record: RebalanceRecord | None = None
