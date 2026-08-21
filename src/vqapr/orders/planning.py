"""Deterministic execution-time conversion from complete targets to venue orders."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
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
    tradable: Mapping[str, bool],
) -> dict[str, Decimal]:
    """Convert intended positions into positions the venue can actually trade.

    Deltas are rounded toward zero onto the listing unit. If the rounded buys cannot be paid for
    out of current cash plus the rounded sell proceeds, buys are clipped in a deterministic order
    until they fit. Nothing is ever rounded up and no order is invented.

    Every charge here names its instrument, so the cash reserved for a buy and released by a sell
    is charged by the same band the venue will charge at the fill. A tax-exempt sleeve that were
    priced venue-wide here would have its buys clipped against money it never owed.

    ``tradable`` is **this instant's** tradability, which is not the same question as
    ``rules.tradable()``. That one is the venue's standing declaration -- listed, never fillable.
    This one is the execution row: a halted name still carries a price, because a halt suspends
    trading and not valuation, and canon 6.1 marks a position from exactly such a row. Funding a
    buy from its sale reserves money that is never going to arrive, and the account is overdrawn
    the moment the venue publishes the refusal as typed ``NONTRADABLE`` evidence.

    The order is still emitted. The refusal is the evidence that the fund tried and the market
    would not let it; only the funding arithmetic declines to count on it.
    """

    def _fillable(instrument_id: str) -> bool:
        return tradable.get(instrument_id, True)

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
        if delta >= 0 or instrument_id not in prices or not _fillable(instrument_id):
            continue
        notional = rules.notional(instrument_id, delta, prices[instrument_id])
        available += notional - rules.charge(Side.SELL, notional, instrument_id).total

    for instrument_id in ordered:
        delta = _delta(instrument_id)
        if delta <= 0 or instrument_id not in prices or not _fillable(instrument_id):
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

    return _settle_payable(
        rules=rules,
        account=account,
        prices=prices,
        resolved=resolved,
        ordered=ordered,
        fillable=_fillable,
    )


def _projected_cash(
    *,
    rules: ExchangeRulesView,
    account: AccountSnapshot,
    prices: Mapping[str, Decimal],
    resolved: Mapping[str, Decimal],
    ordered: Sequence[str],
    fillable: Callable[[str], bool],
) -> Decimal:
    """The cash the account will hold once this batch is charged, in the account's own order.

    ``Account.prepare_fill`` accumulates ``Fill.cash_delta`` over fills sorted by instrument. This
    walks the same sequence with the same terms, so the number it returns is the number the
    account will compute -- including where ``Decimal`` rounds.
    """
    cash = account.cash
    for instrument_id in ordered:
        delta = resolved[instrument_id] - account.positions.get(instrument_id, Decimal(0))
        if delta == 0 or instrument_id not in prices or not fillable(instrument_id):
            continue
        price = prices[instrument_id]
        notional = rules.notional(instrument_id, delta, price)
        side = Side.BUY if delta > 0 else Side.SELL
        cash -= delta * price + rules.charge(side, notional, instrument_id).total
    return cash


def _settle_payable(
    *,
    rules: ExchangeRulesView,
    account: AccountSnapshot,
    prices: Mapping[str, Decimal],
    resolved: dict[str, Decimal],
    ordered: Sequence[str],
    fillable: Callable[[str], bool],
) -> dict[str, Decimal]:
    """Guarantee the batch is payable under the arithmetic the account will actually use.

    The clip above reserves cash term by term and the account charges fill by fill. Those two sums
    are algebraically identical and **not** identical in ``Decimal``: a notional here already uses
    all 28 significant digits, so the same money summed in a different order can differ in the
    last one. A book that leaves cash never notices. A fully-invested book -- ``cash_target = 0``,
    which is what an enhanced index holding its sleeve as a position declares -- lands within one
    ulp of zero, and ``Account.prepare_fill`` refuses *any* negative:

        cash before     3.516E-18
        sell proceeds   1333510283.370090515324773564
        buy required    1333510283.370090515324773570
        projected      -2E-18                          <- run over

    So the planner checks its own batch the way the account will, and shaves the largest buy by
    whole lots until it is payable. Shaving the largest is deliberate: it is the position least
    disturbed in relative terms, and it is deterministic, which a batch that must replay exactly
    requires.
    """
    for _ in range(MAX_AFFORDABILITY_STEPS):
        projected = _projected_cash(
            rules=rules,
            account=account,
            prices=prices,
            resolved=resolved,
            ordered=ordered,
            fillable=fillable,
        )
        if projected >= 0:
            return resolved
        buys = [
            instrument_id
            for instrument_id in ordered
            if instrument_id in prices
            and fillable(instrument_id)
            and resolved[instrument_id]
            > account.positions.get(instrument_id, Decimal(0))
        ]
        if not buys:
            # Nothing was bought, so the shortfall is not this batch's to fix: an account that
            # cannot pay for its own sales is a venue charging more than it declared.
            raise ValueError(
                f"a sell-only batch on {rules.exchange_id!r} would still overdraw the account by "
                f"{-projected}; the venue charges more than its declared band"
            )
        largest = max(
            buys,
            key=lambda instrument_id: (
                rules.notional(
                    instrument_id,
                    resolved[instrument_id]
                    - account.positions.get(instrument_id, Decimal(0)),
                    prices[instrument_id],
                ),
                instrument_id,
            ),
        )
        step = rules.listing(largest).quantity_step
        held = account.positions.get(largest, Decimal(0))
        shaved = rules.quantize(largest, resolved[largest] - held - step)
        resolved[largest] = held + max(shaved, Decimal(0))
    raise ValueError(
        f"batch on {rules.exchange_id!r} could not be made payable within "
        f"{MAX_AFFORDABILITY_STEPS} lots; planning and the account disagree by more than rounding"
    )


def plan_orders(
    *,
    account: AccountSnapshot,
    execution_time_nav: Decimal,
    prices: Mapping[str, Decimal],
    weight_targets: Mapping[str, Decimal],
    cash_target: Decimal,
    budget: Budget,
    rules: ExchangeRulesView | None = None,
    tradable: Mapping[str, bool] | None = None,
) -> OrderBatch:
    """Convert a weight target into the delta that reaches it at execution-time prices.

    This is the only place a weight becomes a quantity. The Strategy declared its target one
    evaluation earlier against prices that have since moved, so the conversion belongs here,
    where the execution price and NAV are both known.

    Held positions always require a selected value. A target-only missing row remains an
    unresolved request so the Exchange can publish typed ``ABSENT`` zero-dealt evidence.

    ``tradable`` carries the execution row's own ``is_tradable`` per instrument. An instrument
    absent from it is assumed fillable, which keeps every caller that does not know about halts
    working exactly as before; a caller that passes it stops funding buys from sales the venue is
    going to refuse.
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
            tradable=dict(tradable or {}),
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
