"""Deterministic execution-time conversion from complete targets to Academic orders."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from vqapr.account.snapshot import AccountSnapshot
from vqapr.orders.batches import OrderBatch, OrderRequest, ZeroDeltaDiagnostic


def _decimal(value: object, *, name: str, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _targets(values: Mapping[str, Decimal], *, name: str) -> dict[str, Decimal]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    result: dict[str, Decimal] = {}
    for instrument_id, value in values.items():
        if not isinstance(instrument_id, str) or not instrument_id:
            raise ValueError(f"{name} keys must be non-empty strings")
        result[instrument_id] = _decimal(value, name=f"{name}[{instrument_id!r}]")
    return result


def _prices(values: Mapping[str, Decimal]) -> dict[str, Decimal]:
    if not isinstance(values, Mapping):
        raise TypeError("prices must be a mapping")
    result: dict[str, Decimal] = {}
    for instrument_id, value in values.items():
        if not isinstance(instrument_id, str) or not instrument_id:
            raise ValueError("prices keys must be non-empty strings")
        result[instrument_id] = _decimal(value, name=f"prices[{instrument_id!r}]", positive=True)
    return result


def plan_orders(
    *,
    account: AccountSnapshot,
    execution_time_nav: Decimal,
    prices: Mapping[str, Decimal],
    weight_targets: Mapping[str, Decimal],
    quantity_targets: Mapping[str, Decimal],
) -> OrderBatch:
    """Plan every targeted or held position using the supplied execution-time NAV.

    Weight targets are converted at the selected execution price. Quantity targets are
    already complete desired quantities and therefore never depend on NAV or price gaps.
    """
    if not isinstance(account, AccountSnapshot):
        raise TypeError("account must be an AccountSnapshot")
    nav = _decimal(execution_time_nav, name="execution_time_nav")
    if nav < 0:
        raise ValueError("execution_time_nav must be non-negative")
    selected_prices = _prices(prices)
    weights = _targets(weight_targets, name="weight_targets")
    quantities = _targets(quantity_targets, name="quantity_targets")
    overlap = set(weights).intersection(quantities)
    if overlap:
        raise ValueError("an instrument may have either a weight target or a quantity target")

    instruments = set(account.positions).union(weights, quantities)
    requests: list[OrderRequest] = []
    diagnostics: list[ZeroDeltaDiagnostic] = []
    for instrument_id in instruments:
        try:
            price = selected_prices[instrument_id]
        except KeyError as error:
            raise ValueError(f"missing selected execution price for {instrument_id!r}") from error
        current = account.positions.get(instrument_id, Decimal(0))
        if instrument_id in weights:
            desired = weights[instrument_id] * nav / price
        elif instrument_id in quantities:
            desired = quantities[instrument_id]
        else:
            desired = Decimal(0)
        request = OrderRequest(
            instrument_id=instrument_id,
            current_quantity=current,
            desired_quantity=desired,
            delta_quantity=desired - current,
            execution_price=price,
        )
        requests.append(request)
        if request.delta_quantity == 0:
            diagnostics.append(
                ZeroDeltaDiagnostic(
                    instrument_id=instrument_id,
                    current_quantity=current,
                    desired_quantity=desired,
                    execution_price=price,
                )
            )

    requests.sort(
        key=lambda request: (
            0 if request.delta_quantity < 0 else 1 if request.delta_quantity == 0 else 2,
            request.instrument_id,
        )
    )
    diagnostics.sort(key=lambda diagnostic: diagnostic.instrument_id)
    return OrderBatch(
        account_version=account.version,
        requests=tuple(requests),
        zero_delta_diagnostics=tuple(diagnostics),
    )
