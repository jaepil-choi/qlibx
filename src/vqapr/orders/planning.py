"""Deterministic execution-time conversion from complete targets to venue orders."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal

from vqapr.account.snapshot import AccountSnapshot
from vqapr.domain.enums import Side
from vqapr.domain.instruments import base_quantity_for
from vqapr.exchange.listings import ExchangeRulesView
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


MAX_AFFORDABILITY_STEPS = 8
"""Corrective lots allowed after the closed-form guess, before the planner refuses.

The guess is exact whenever a venue charges a rate on notional, which every shipped cost band
does, so zero corrective steps is the normal case. A venue whose ``notional`` is genuinely
non-linear in quantity may need a few; one that needs more than this is not merely non-linear but
non-monotone, and walking further would be searching rather than correcting.
"""


def _affordable_quantity(
    *,
    rules: ExchangeRulesView,
    instrument_id: str,
    price: Decimal,
    available: Decimal,
) -> Decimal:
    """The largest quantity of ``instrument_id`` that ``available`` cash actually pays for.

    Solved, not searched. A buy costs ``notional(q) + charge(notional(q))``, and a cost band is a
    rate on notional, so

        required(q) = notional(q) * (1 + commission_rate + tax_rate)

    and the affordable notional is ``available / (1 + rate)``. The conversion back to a quantity
    goes through the venue, so a category whose contract is not one unit of the quoted price -- a
    future with a multiplier -- keeps working.

    The previous implementation guessed ``available / price``, which ignores the commission and so
    always overshoots by the charge on itself, then removed the overshoot **one quantity_step at a
    time**. That walk is ``affordable * rate / step`` iterations: 55 on a whole-share venue with
    10bn of cash to spend, and 55,226,256 for the same cash on a venue whose step is 1e-6. Both
    shipped KRX profiles trade whole shares, which is why nothing exercised it -- and a fractional
    academic venue, which is what alpha research runs on, could not finish a single session.

    The bounded loop below corrects the guess for ``quantize`` flooring; it does not search. It
    refuses rather than return a quantity the account cannot pay for.
    """
    cost = rules.listing(instrument_id).cost(Side.BUY)
    rate = Decimal(1) + cost.commission_rate + cost.tax_rate
    affordable = rules.quantize(
        instrument_id, rules.quantity_for(instrument_id, available / rate, price)
    )
    for _ in range(MAX_AFFORDABILITY_STEPS):
        if affordable <= 0:
            return Decimal(0)
        notional = rules.notional(instrument_id, affordable, price)
        if notional + rules.charge(Side.BUY, notional, instrument_id).total <= available:
            return affordable
        affordable = rules.quantize(
            instrument_id, affordable - rules.listing(instrument_id).quantity_step
        )
    raise ValueError(
        f"affordable quantity for {instrument_id!r} on {rules.exchange_id!r} did not converge "
        f"within {MAX_AFFORDABILITY_STEPS} lots of the closed-form estimate; the venue's notional "
        "or cost is not monotone in quantity"
    )


def _apply_venue_rules(
    *,
    rules: ExchangeRulesView,
    account: AccountSnapshot,
    prices: Mapping[str, Decimal],
    desired: Mapping[str, Decimal],
    instruments: Iterable[str],
) -> dict[str, Decimal]:
    """Convert intended positions into positions the venue can actually trade.

    Deltas are rounded toward zero onto the listing unit. If the rounded buys cannot be paid for
    out of current cash plus the rounded sell proceeds, buys are clipped in a deterministic order
    until they fit. Nothing is ever rounded up and no order is invented.

    Every charge here names its instrument, so the cash reserved for a buy and released by a sell
    is charged by the same band the venue will charge at the fill. A tax-exempt sleeve that were
    priced venue-wide here would have its buys clipped against money it never owed.
    """
    ordered = sorted(instruments)
    resolved: dict[str, Decimal] = {}
    for instrument_id in ordered:
        current = account.positions.get(instrument_id, Decimal(0))
        if instrument_id not in prices:
            resolved[instrument_id] = desired[instrument_id]
            continue
        if not rules.tradable(instrument_id) and desired[instrument_id] != current:
            # The venue lists it but permits no side. Refuse here, where the target that asked
            # for it is still visible; the venue would otherwise refuse the whole batch and the
            # message would name a side rather than the instruction that produced it.
            raise ValueError(
                f"{instrument_id!r} permits no side on {rules.exchange_id!r} and cannot be traded"
            )
        delta = rules.quantize(instrument_id, desired[instrument_id] - current)
        resolved[instrument_id] = current + delta

    def _delta(instrument_id: str) -> Decimal:
        return resolved[instrument_id] - account.positions.get(instrument_id, Decimal(0))

    available = account.cash
    for instrument_id in ordered:
        delta = _delta(instrument_id)
        if delta >= 0 or instrument_id not in prices:
            continue
        notional = rules.notional(instrument_id, delta, prices[instrument_id])
        available += notional - rules.charge(Side.SELL, notional, instrument_id).total

    for instrument_id in ordered:
        delta = _delta(instrument_id)
        if delta <= 0 or instrument_id not in prices:
            continue
        price = prices[instrument_id]
        notional = rules.notional(instrument_id, delta, price)
        required = notional + rules.charge(Side.BUY, notional, instrument_id).total
        if required <= available:
            available -= required
            continue
        affordable = _affordable_quantity(
            rules=rules, instrument_id=instrument_id, price=price, available=available
        )
        if affordable <= 0:
            resolved[instrument_id] = account.positions.get(instrument_id, Decimal(0))
            continue
        notional = rules.notional(instrument_id, affordable, price)
        available -= notional + rules.charge(Side.BUY, notional, instrument_id).total
        resolved[instrument_id] = account.positions.get(instrument_id, Decimal(0)) + affordable
    return resolved


def plan_orders(
    *,
    account: AccountSnapshot,
    execution_time_nav: Decimal,
    prices: Mapping[str, Decimal],
    weight_targets: Mapping[str, Decimal],
    cash_target: Decimal,
    budget: Budget,
    rules: ExchangeRulesView | None = None,
) -> OrderBatch:
    """Convert a weight target into the delta that reaches it at execution-time prices.

    This is the only place a weight becomes a quantity. The Strategy declared its target one
    evaluation earlier against prices that have since moved, so the conversion belongs here,
    where the execution price and NAV are both known.

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
    if sum(weights.values(), Decimal(0)) + cash != 1:
        raise ValueError("weight targets plus cash_target must equal one")

    instruments = set(account.positions).union(weights)

    desired_quantities: dict[str, Decimal] = {}
    unresolved_weights: dict[str, Decimal] = {}
    for instrument_id in instruments:
        price = selected_prices.get(instrument_id)
        held = account.positions.get(instrument_id, Decimal(0))
        if price is None:
            # The venue cannot price this instrument now. A holding stays exactly where it is --
            # an unpriceable position cannot be sold, and closing it at an invented price would
            # fabricate the proceeds -- and the Exchange publishes typed ABSENT evidence for it.
            desired = held
            allocation = weights.get(instrument_id, Decimal(0))
            if instrument_id in weights:
                unresolved_weights[instrument_id] = allocation
        elif instrument_id in weights:
            # The one place a weight becomes a quantity. Routed through the venue so a category
            # whose contract is not one unit of the quoted price sizes correctly here too.
            exposure = weights[instrument_id] * nav
            desired = (
                base_quantity_for(exposure, price)
                if rules is None
                else rules.quantity_for(instrument_id, exposure, price)
            )
            allocation = weights[instrument_id]
        else:
            desired = Decimal(0)
            allocation = Decimal(0)
        if budget.direction is PortfolioDirection.LONG_ONLY and desired < 0:
            raise ValueError("long_only budget forbids negative desired positions")
        if not budget.validates_target(allocation):
            raise ValueError("complete desired position is outside the declared budget bounds")
        desired_quantities[instrument_id] = desired

    if rules is not None:
        desired_quantities = _apply_venue_rules(
            rules=rules,
            account=account,
            prices=selected_prices,
            desired=desired_quantities,
            instruments=instruments,
        )

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
