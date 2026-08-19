"""Closed order-planning envelopes for the Academic execution path."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


def _decimal(value: Decimal, *, name: str, positive: bool = False) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")


def _instrument(value: str, *, name: str = "instrument_id") -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """A complete desired position, or an unresolved request the venue could not price.

    An unresolved request carries no execution price. That happens two ways: a target for an
    instrument absent from the venue at this instant, and a holding whose instrument has left it
    -- a delisting. The second keeps its quantity and asks for no trade, because a position that
    cannot be priced also cannot be sold, and inventing a price to close it would fabricate the
    proceeds.
    """

    instrument_id: str
    current_quantity: Decimal
    desired_quantity: Decimal
    delta_quantity: Decimal
    execution_price: Decimal | None
    unresolved_weight_target: Decimal | None = None

    def __post_init__(self) -> None:
        _instrument(self.instrument_id)
        _decimal(self.current_quantity, name="current_quantity")
        _decimal(self.desired_quantity, name="desired_quantity")
        _decimal(self.delta_quantity, name="delta_quantity")
        if self.delta_quantity != self.desired_quantity - self.current_quantity:
            raise ValueError("delta_quantity must equal desired_quantity - current_quantity")
        if self.execution_price is None:
            # An unpriced target may still be requested: the venue answers with typed ABSENT
            # evidence. What it may not do is move an existing holding, because settling a
            # position needs a price and inventing one would fabricate the proceeds.
            if self.current_quantity != 0 and self.desired_quantity != self.current_quantity:
                raise ValueError("an unresolved request cannot settle an existing holding")
            if self.unresolved_weight_target is not None:
                _decimal(
                    self.unresolved_weight_target,
                    name="unresolved_weight_target",
                )
                if self.desired_quantity != self.current_quantity:
                    raise ValueError(
                        "an unresolved weight request cannot invent a desired quantity"
                    )
            return
        _decimal(self.execution_price, name="execution_price", positive=True)
        if self.unresolved_weight_target is not None:
            raise ValueError("a priced request cannot have an unresolved weight target")


@dataclass(frozen=True, slots=True)
class ZeroDeltaDiagnostic:
    """Typed evidence that a complete target intentionally needs no trade."""

    instrument_id: str
    current_quantity: Decimal
    desired_quantity: Decimal
    execution_price: Decimal

    def __post_init__(self) -> None:
        _instrument(self.instrument_id)
        _decimal(self.current_quantity, name="current_quantity")
        _decimal(self.desired_quantity, name="desired_quantity")
        _decimal(self.execution_price, name="execution_price", positive=True)
        if self.current_quantity != self.desired_quantity:
            raise ValueError(
                "a zero-delta diagnostic requires equal current and desired quantities"
            )


@dataclass(frozen=True, slots=True)
class OrderBatch:
    """Deterministic complete-position order plan bound to an account version."""

    account_version: int
    requests: tuple[OrderRequest, ...]
    zero_delta_diagnostics: tuple[ZeroDeltaDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.account_version, bool) or not isinstance(self.account_version, int):
            raise TypeError("account_version must be an integer")
        if self.account_version < 0:
            raise ValueError("account_version must be non-negative")
        if not isinstance(self.requests, tuple) or any(
            not isinstance(request, OrderRequest) for request in self.requests
        ):
            raise TypeError("requests must be a tuple of OrderRequest")
        if not isinstance(self.zero_delta_diagnostics, tuple) or any(
            not isinstance(diagnostic, ZeroDeltaDiagnostic)
            for diagnostic in self.zero_delta_diagnostics
        ):
            raise TypeError("zero_delta_diagnostics must be a tuple of ZeroDeltaDiagnostic")
        instruments = tuple(request.instrument_id for request in self.requests)
        if len(instruments) != len(set(instruments)):
            raise ValueError("an OrderBatch may contain each instrument only once")
        zeros = tuple(diagnostic.instrument_id for diagnostic in self.zero_delta_diagnostics)
        if len(zeros) != len(set(zeros)):
            raise ValueError("zero-delta diagnostics may contain each instrument only once")
        requests_by_instrument = {request.instrument_id: request for request in self.requests}
        for diagnostic in self.zero_delta_diagnostics:
            request = requests_by_instrument.get(diagnostic.instrument_id)
            if request is None or request.delta_quantity != 0:
                raise ValueError("zero-delta diagnostics require a matching zero-delta request")
