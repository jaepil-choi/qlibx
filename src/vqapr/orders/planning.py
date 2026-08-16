"""Deterministic execution-time conversion from complete targets to Academic orders."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from vqapr.account.snapshot import AccountSnapshot
from vqapr.orders.batches import OrderBatch, OrderRequest, ZeroDeltaDiagnostic
from vqapr.portfolio.budgets import Budget, PortfolioDirection


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
    cash_target: Decimal,
    budget: Budget,
) -> OrderBatch:
    """Plan a complete target portfolio against execution-time NAV.

    Held positions always require a selected value. A target-only missing row remains an
    unresolved request so the Exchange can publish typed ``ABSENT`` zero-dealt evidence.
    """
    if not isinstance(account, AccountSnapshot):
        raise TypeError("account must be an AccountSnapshot")
    nav = _decimal(execution_time_nav, name="execution_time_nav", positive=True)
    cash = _decimal(cash_target, name="cash_target")
    if not isinstance(budget, Budget):
        raise TypeError("budget must be a Budget")
    if not budget.validates_cash(cash):
        raise ValueError("cash_target is outside the declared budget")
    selected_prices = _prices(prices)
    weights = _targets(weight_targets, name="weight_targets")
    quantities = _targets(quantity_targets, name="quantity_targets")
    overlap = set(weights).intersection(quantities)
    if overlap:
        raise ValueError("an instrument may have either a weight target or a quantity target")
    if not quantities and sum(weights.values(), Decimal(0)) + cash != 1:
        raise ValueError("weight targets plus cash_target must equal one")

    instruments = set(account.positions).union(weights, quantities)
    missing_held = sorted(
        instrument_id
        for instrument_id, quantity in account.positions.items()
        if quantity != 0 and instrument_id not in selected_prices
    )
    if missing_held:
        raise ValueError(f"missing selected execution price for held instruments: {missing_held}")

    desired_quantities: dict[str, Decimal] = {}
    unresolved_weights: dict[str, Decimal] = {}
    for instrument_id in instruments:
        if instrument_id in weights:
            price = selected_prices.get(instrument_id)
            desired = Decimal(0) if price is None else weights[instrument_id] * nav / price
            allocation = weights[instrument_id]
            if price is None:
                unresolved_weights[instrument_id] = allocation
        elif instrument_id in quantities:
            desired = quantities[instrument_id]
            allocation = desired
        else:
            desired = Decimal(0)
            allocation = Decimal(0)
        if budget.direction is PortfolioDirection.LONG_ONLY and desired < 0:
            raise ValueError("long_only budget forbids negative desired positions")
        if not budget.validates_target(allocation):
            raise ValueError("complete desired position is outside the declared budget bounds")
        desired_quantities[instrument_id] = desired

    unresolved_targets = (set(weights) | set(quantities)).difference(selected_prices)
    if quantities and not unresolved_targets:
        post_trade_cash = nav - sum(
            (
                desired_quantities[instrument_id] * selected_prices[instrument_id]
                for instrument_id in instruments
            ),
            Decimal(0),
        )
        if post_trade_cash != nav * cash:
            raise ValueError("complete desired positions do not produce the declared cash_target")

    requests: list[OrderRequest] = []
    diagnostics: list[ZeroDeltaDiagnostic] = []
    for instrument_id in instruments:
        current = account.positions.get(instrument_id, Decimal(0))
        price = selected_prices.get(instrument_id)
        desired = desired_quantities[instrument_id]
        request = OrderRequest(
            instrument_id=instrument_id,
            current_quantity=current,
            desired_quantity=desired,
            delta_quantity=desired - current,
            execution_price=price,
            unresolved_weight_target=unresolved_weights.get(instrument_id),
        )
        requests.append(request)
        if request.delta_quantity == 0 and price is not None:
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
