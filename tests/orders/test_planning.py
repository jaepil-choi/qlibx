from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.domain.enums import Side
from vqapr.domain.instruments import InstrumentKind, instrument
from vqapr.domain.roster import InstrumentRoster
from vqapr.exchange.costs import SideCost
from vqapr.exchange.fills import Fill, FillBatch, ZeroDealtReason
from vqapr.exchange.listings import (
    ExchangeRulesView,
    ListingAccess,
    TradeRule,
    TradeTerms,
    rules_view,
)
from vqapr.orders.planning import plan_orders
from vqapr.portfolio.budgets import Budget, PortfolioDirection
from vqapr.valuation.marking import ValuationService


def decimal(value: str) -> Decimal:
    return Decimal(value)


_BUDGET = Budget(
    PortfolioDirection.LONG_ONLY, decimal("0"), decimal("1"), decimal("0"), decimal("1")
)



def snapshot(
    *, version: int = 3, cash: str = "100", positions: dict[str, str] | None = None
) -> AccountSnapshot:
    return AccountSnapshot(
        version=version,
        cash=decimal(cash),
        positions={key: decimal(value) for key, value in (positions or {}).items()},
    )


def test_weight_target_uses_execution_time_nav_after_a_price_gap() -> None:
    batch = plan_orders(
        account=snapshot(positions={"A": "1"}),
        execution_time_nav=decimal("200"),
        prices={"A": decimal("40")},
        weight_targets={"A": decimal("0.5")},
        cash_target=decimal("0.5"),
        budget=_BUDGET,
    )

    assert batch.requests[0].desired_quantity == decimal("2.5")
    assert batch.requests[0].delta_quantity == decimal("1.5")


def test_omitted_holding_is_a_zero_target_and_sells_precede_buys() -> None:
    batch = plan_orders(
        account=snapshot(positions={"Z": "3", "A": "1"}),
        execution_time_nav=decimal("100"),
        prices={"Z": decimal("10"), "A": decimal("10"), "B": decimal("10")},
        weight_targets={"A": decimal("0.1"), "B": decimal("0.2")},
        cash_target=decimal("0.7"),
        budget=_BUDGET,
    )

    assert [(order.instrument_id, order.delta_quantity) for order in batch.requests] == [
        ("Z", decimal("-3")),
        ("A", decimal("0")),
        ("B", decimal("2")),
    ]
    assert [diagnostic.instrument_id for diagnostic in batch.zero_delta_diagnostics] == ["A"]


def test_an_unchanged_weight_target_needs_no_trade_after_a_price_move() -> None:
    """Price drift alone must not manufacture an order.

    The holding is already exactly the target fraction of the moved NAV, so converting the
    weight at execution-time prices lands on the quantity already held.
    """
    batch = plan_orders(
        account=snapshot(cash="0", positions={"A": "10", "B": "10"}),
        execution_time_nav=decimal("400"),
        prices={"A": decimal("30"), "B": decimal("10")},
        weight_targets={"A": decimal("0.75"), "B": decimal("0.25")},
        cash_target=decimal("0"),
        budget=_BUDGET,
    )

    assert [order.delta_quantity for order in batch.requests] == [decimal("0"), decimal("0")]
    assert [diagnostic.instrument_id for diagnostic in batch.zero_delta_diagnostics] == ["A", "B"]


def test_complete_desired_positions_enforce_budget_direction_and_bounds() -> None:
    with pytest.raises(ValueError, match="long_only"):
        plan_orders(
            account=snapshot(),
            execution_time_nav=decimal("100"),
            prices={"A": decimal("10")},
            weight_targets={"A": decimal("-0.1")},
            cash_target=decimal("1.1"),
            budget=Budget(
                PortfolioDirection.LONG_ONLY,
                decimal("0"),
                decimal("2"),
                decimal("-1"),
                decimal("1"),
            ),
        )
    with pytest.raises(ValueError, match="budget bounds"):
        plan_orders(
            account=snapshot(),
            execution_time_nav=decimal("100"),
            prices={"A": decimal("10")},
            weight_targets={"A": decimal("0.7")},
            cash_target=decimal("0.3"),
            budget=Budget(
                PortfolioDirection.LONG_ONLY,
                decimal("0"),
                decimal("1"),
                decimal("0"),
                decimal("0.6"),
            ),
        )


def test_missing_target_only_price_remains_an_unresolved_exchange_request() -> None:
    weight = plan_orders(
        account=snapshot(),
        execution_time_nav=decimal("100"),
        prices={},
        weight_targets={"A": decimal("0.25")},
        cash_target=decimal("0.75"),
        budget=_BUDGET,
    )
    assert weight.requests[0].execution_price is None
    assert weight.requests[0].unresolved_weight_target == decimal("0.25")
    assert weight.requests[0].desired_quantity == decimal("0")


def test_an_unpriceable_holding_is_kept_rather_than_ending_the_batch() -> None:
    """A delisted holding is a market fact, not a data-contract breach.

    Canon 6.1 assigns an absent row to zero-dealt evidence. Refusing here would end a run on the
    first delisting, so the position is carried at its current quantity, asks for no trade, and
    reaches the Exchange as an unresolved request.
    """
    batch = plan_orders(
        account=snapshot(positions={"HELD": "1"}),
        execution_time_nav=decimal("100"),
        prices={},
        weight_targets={"TARGET": decimal("0.25")},
        cash_target=decimal("0.75"),
        budget=_BUDGET,
    )

    held = next(order for order in batch.requests if order.instrument_id == "HELD")
    assert held.execution_price is None
    assert held.current_quantity == decimal("1")
    assert held.desired_quantity == decimal("1")
    assert held.delta_quantity == decimal("0")


def test_an_unpriceable_holding_is_left_out_of_the_priced_book() -> None:
    """The position stays, but nothing pretends to know what it is worth right now."""
    batch = plan_orders(
        account=snapshot(cash="50", positions={"HELD": "1", "A": "2"}),
        execution_time_nav=decimal("100"),
        prices={"A": decimal("25")},
        weight_targets={"A": decimal("0.5")},
        cash_target=decimal("0.5"),
        budget=_BUDGET,
    )

    priced = next(order for order in batch.requests if order.instrument_id == "A")
    assert priced.desired_quantity == decimal("2")
    assert priced.delta_quantity == decimal("0")


def test_equal_side_orders_use_instrument_tie_break() -> None:
    batch = plan_orders(
        account=snapshot(positions={"Z": "1", "A": "1"}),
        execution_time_nav=decimal("100"),
        prices={"Z": decimal("1"), "A": decimal("1"), "B": decimal("1")},
        weight_targets={"B": decimal("1")},
        cash_target=decimal("0"),
        budget=_BUDGET,
    )

    assert [order.instrument_id for order in batch.requests] == ["A", "Z", "B"]


def test_account_transition_validation_does_not_mutate_the_root() -> None:
    account = Account(mode=AccountMode.LONG_ONLY)
    mutable_positions = {"A": decimal("1")}
    copied = AccountSnapshot(3, decimal("100"), mutable_positions)
    mutable_positions["A"] = decimal("9")
    assert copied.positions["A"] == decimal("1")
    with pytest.raises(TypeError):
        copied.positions["A"] = decimal("2")  # type: ignore[index]

    root = AccountState(snapshot(positions={"A": "1"}))
    short = FillBatch((Fill("A", decimal("-2"), decimal("-2"), decimal("10")),), 3)
    with pytest.raises(ValueError, match="short"):
        account.prepare_fill(root, short, expected_version=3)
    unaffordable = FillBatch((Fill("B", decimal("11"), decimal("11"), decimal("10")),), 3)
    with pytest.raises(ValueError, match="cash"):
        account.prepare_fill(root, unaffordable, expected_version=3)
    with pytest.raises(ValueError, match="expected_version"):
        account.prepare_fill(root, short, expected_version=2)
    assert root == AccountState(snapshot(positions={"A": "1"}))


def test_account_prepares_a_complete_fill_and_mark_transition() -> None:
    root = AccountState(snapshot(cash="10"))
    account = Account(mode=AccountMode.SIGNED)
    fills = FillBatch(
        (
            Fill("A", decimal("1"), decimal("1"), decimal("4")),
            Fill("B", decimal("-1"), Decimal(0), None, ZeroDealtReason.ABSENT),
        ),
        3,
    )

    prepared_fill = account.prepare_fill(root, fills, expected_version=3)
    transition = account.prepare_mark(
        prepared_fill,
        ValuationService().mark(prepared_fill.next_snapshot, {"A": decimal("4")}),
        provenance="test",
    )

    assert transition.next_state.snapshot == AccountSnapshot(4, decimal("6"), {"A": decimal("1")})
    assert len(transition.next_state.fill_history) == 2
    assert transition.next_state.latest_mark is not None
    assert root == AccountState(snapshot(cash="10"))


def test_zero_dealt_fills_prepare_an_unchanged_account_snapshot() -> None:
    root = AccountState(snapshot(cash="10", positions={"HELD": "2"}))
    account = Account(mode=AccountMode.LONG_ONLY)
    before = root.snapshot
    fills = FillBatch(
        (
            Fill("TARGET", decimal("3"), Decimal(0), None, ZeroDealtReason.ABSENT),
            Fill("PAUSED", decimal("-1"), Decimal(0), None, ZeroDealtReason.NONTRADABLE),
        ),
        before.version,
    )

    prepared = account.prepare_fill(root, fills, expected_version=before.version)

    assert prepared.next_snapshot.cash == before.cash
    assert prepared.next_snapshot.positions == before.positions


def _fractional_venue(instrument_id: str, *, step: str, commission: str) -> ExchangeRulesView:
    """An academic venue whose lot is as fine as the caller says, charging one rate on buys."""
    rule = TradeRule(
        instrument_id,
        decimal(step),
        decimal(step),
        True,
        ListingAccess.LONG_ONLY,
        SideCost(commission_rate=decimal(commission)),
        SideCost(),
    )
    return rules_view("fractional", {instrument_id: rule})


def test_buys_are_funded_largest_delta_first_not_in_ticker_order() -> None:
    """Canon 6.3. What a refused buy costs is measured by its delta, so the largest is funded
    first and the shortfall lands on the position that misses its target by least.

    Ordering by ``instrument_id`` made the loser depend on ticker spelling: an ETF sleeve listed
    as ``A069500`` sorts behind most of a KRX universe and was clipped for that reason alone.
    """
    small, big = "A000001", "Z999999"          # the big target sorts last alphabetically
    # A commission is what makes the plan overrun its cash, so somebody has to be clipped.
    rules = rules_view(
        "whole",
        {
            name: TradeRule(
                name,
                decimal("1"),
                decimal("1"),
                False,
                ListingAccess.LONG_ONLY,
                SideCost(commission_rate=decimal("0.0003")),
                SideCost(),
            )
            for name in (small, big)
        },
    )
    nav = decimal("1000000")
    batch = plan_orders(
        account=snapshot(cash="1000000"),
        execution_time_nav=nav,
        prices={small: decimal("10000"), big: decimal("10000")},
        weight_targets={small: decimal("0.1"), big: decimal("0.9")},
        cash_target=decimal("0"),
        budget=_BUDGET,
        rules=rules,
    )
    planned = {request.instrument_id: request.delta_quantity for request in batch.requests}

    assert planned[big] == decimal("90"), "the largest delta is funded in full"
    assert planned[small] == decimal("9"), "the shortfall lands on the smallest delta"


def test_buy_order_compares_money_rather_than_share_count() -> None:
    """One share of a 900,000 name and one of a 9,000 name are not the same intent."""
    cheap, dear = "AAA", "ZZZ"
    rules = rules_view(
        "whole",
        {
            name: TradeRule(
                name,
                decimal("1"),
                decimal("1"),
                False,
                ListingAccess.LONG_ONLY,
                SideCost(commission_rate=decimal("0.0003")),
                SideCost(),
            )
            for name in (cheap, dear)
        },
    )
    nav = decimal("1000000")
    # `cheap` wants far more shares; `dear` wants far more money and must be funded first.
    batch = plan_orders(
        account=snapshot(cash="1000000"),
        execution_time_nav=nav,
        prices={cheap: decimal("1000"), dear: decimal("300000")},
        weight_targets={cheap: decimal("0.1"), dear: decimal("0.9")},
        cash_target=decimal("0"),
        budget=_BUDGET,
        rules=rules,
    )
    planned = {request.instrument_id: request.delta_quantity for request in batch.requests}

    # `dear` sorts last alphabetically and wants only 3 shares, but it is 900,000 of intent.
    assert planned[dear] == decimal("3"), "900,000 of intent is funded before 100,000 of it"
    assert planned[cheap] == decimal("99"), "the shortfall lands on the smaller money line"


def test_an_unaffordable_buy_is_clipped_by_arithmetic_not_by_walking_lots() -> None:
    """The clip is solved, not searched, so a fine lot does not cost proportionally more.

    A buy that overruns the cash available is reduced to what the cash pays for. That quantity has
    a closed form, because a cost band is a rate on notional. The previous implementation instead
    walked down one ``quantity_step`` per iteration from a guess that ignored the commission --
    ``affordable * rate / step`` iterations, which is 55 for the whole-share venues that ship and
    55,226,256 for the same money on the 1e-6 lot a fractional academic profile declares. A run on
    such a venue could not finish a session.

    Asserted as behaviour rather than as a timing: the same book planned on three lot sizes
    spanning six orders of magnitude must be payable, must leave less than one lot unspent, and
    must not shrink as the lot gets finer.
    """
    price = decimal("54321.9876")
    commission = decimal("0.0003")
    cash = decimal("10000000000")

    planned: dict[str, Decimal] = {}
    for step in ("1", "0.001", "0.000001"):
        batch = plan_orders(
            account=AccountSnapshot(0, cash, {}),
            execution_time_nav=cash,
            prices={"A": price},
            weight_targets={"A": decimal("1")},
            cash_target=decimal("0"),
            budget=_BUDGET,
            rules=_fractional_venue("A", step=step, commission=str(commission)),
        )
        quantity = batch.requests[0].delta_quantity
        planned[step] = quantity

        charged = quantity * price * (Decimal(1) + commission)
        assert charged <= cash, f"step {step} planned a buy the account cannot pay for"
        over = (quantity + decimal(step)) * price * (Decimal(1) + commission)
        assert over > cash, f"step {step} left a whole lot of affordable cash unspent"

    assert planned["0.000001"] >= planned["0.001"] >= planned["1"], (
        "a finer lot must reach at least as much of the budget as a coarser one"
    )
    assert planned["1"] * price >= cash * decimal("0.999"), (
        "the clip must land near the budget, not far below it"
    )


def test_a_category_driven_venue_sizes_a_large_buy_from_the_channel_that_bills() -> None:
    """Issue `078`, the defect that stopped three real ensemble books.

    A venue whose rate follows the category declares `terms_by_kind` and leaves every
    `TradeRule`'s `buy`/`sell` alone -- `venue.py:66` states that as the rule, because baking a
    rate into each listing is holding a second copy of a fact the project owns (issue `013`).
    The planner's affordability estimate read those untouched defaults, which are zero on both
    fields, so it sized as if the buy were free, overshot by the whole commission the fill was
    then charged, and the bounded correction could not close a gap that is a fraction of the
    order. The run ended on `did not converge`.
    """
    rate = decimal("0.0025")
    listing = TradeRule(
        "A",
        decimal("1"),
        decimal("1"),
        False,
        ListingAccess.LONG_ONLY,
        SideCost(),
        SideCost(),
    )
    rules = ExchangeRulesView(
        "category-driven",
        {"A": listing},
        terms_by_kind={
            InstrumentKind.STOCK: TradeTerms(
                decimal("1"),
                decimal("1"),
                False,
                buy=SideCost(commission_rate=rate),
                sell=SideCost(commission_rate=rate),
            )
        },
    ).with_registry(InstrumentRoster({"A": instrument("A", "stock")}))
    cash = decimal("1000000000")
    price = decimal("54321.9876")

    batch = plan_orders(
        account=AccountSnapshot(0, cash, {}),
        execution_time_nav=cash,
        prices={"A": price},
        weight_targets={"A": decimal("1")},
        cash_target=decimal("0"),
        budget=_BUDGET,
        rules=rules,
    )

    quantity = batch.requests[0].delta_quantity
    charged = quantity * price * (Decimal(1) + rate)
    assert charged <= cash, "the planner sized a buy the account cannot pay for"
    assert (quantity + Decimal(1)) * price * (Decimal(1) + rate) > cash, (
        "a whole affordable lot was left unspent"
    )
    # The zero the listing carries is not the number that was used: sizing on it would have
    # planned this many shares and been refused by the account.
    assert quantity < cash / price


def test_a_venue_whose_cost_never_shrinks_leaves_the_cash_rather_than_refusing() -> None:
    """Owner ruling, 2026-09-05 (`078`): leaving cash is fine, so the walk does not refuse.

    This venue bills a flat fee larger than the account, so no size is payable and the descent
    runs out. The planner buys nothing and the cash stays where it is -- the same answer it gives
    when one lot costs more than the cash on hand. It used to raise `did not converge` and assert
    a cause ("the venue's notional or cost is not monotone") that nothing had measured.
    """
    cash = decimal("1000000")

    class _FlatFee(ExchangeRulesView):
        def charge(self, side, notional, instrument_id):  # type: ignore[override]
            return SideCost(commission_rate=decimal("1")).charge(cash * decimal("10"))

    rule = TradeRule(
        "A",
        decimal("0.001"),
        decimal("0.001"),
        True,
        ListingAccess.LONG_ONLY,
        SideCost(commission_rate=decimal("0.0003")),
        SideCost(),
    )

    batch = plan_orders(
        account=AccountSnapshot(0, cash, {}),
        execution_time_nav=cash,
        prices={"A": decimal("54321.9876")},
        weight_targets={"A": decimal("1")},
        cash_target=decimal("0"),
        budget=_BUDGET,
        rules=_FlatFee("flat-fee", {"A": rule}),
    )

    (request,) = batch.requests
    assert request.delta_quantity == Decimal(0), "an unpayable buy must not be planned"
    assert [diagnostic.instrument_id for diagnostic in batch.zero_delta_diagnostics] == ["A"], (
        "the batch must still carry evidence that this name was not traded"
    )


def test_a_halted_sale_does_not_fund_a_buy() -> None:
    """A halt suspends trading, not valuation, so its price must not become spending money.

    The venue publishes a halted sell as typed ``NONTRADABLE`` zero-dealt evidence. If planning
    counted its proceeds, the buys it funded still fill and the account is overdrawn -- which
    `Account.prepare_fill` catches only at the last moment, ending the run. A book with cash slack
    absorbs it silently; a fully-invested one dies on its first halted holding, and on the KOSPI
    200 panel every one of 2,485 sessions carries halted-but-priced rows.

    Only the funding arithmetic changes. The sell is still requested, because the refusal is the
    evidence that the fund tried and the market would not let it.
    """
    price = decimal("10000")
    account = AccountSnapshot(0, decimal("0"), {"HALTED": decimal("100")})
    rules = rules_view(
        "v",
        {
            name: TradeRule(
                name,
                decimal("0.000001"),
                decimal("0.000001"),
                True,
                ListingAccess.SIGNED,
                SideCost(commission_rate=decimal("0.0003")),
                SideCost(commission_rate=decimal("0.0003"), tax_rate=decimal("0.002")),
            )
            for name in ("HALTED", "BUYME")
        },
    )

    def plan(tradable: dict[str, bool] | None) -> dict[str, Decimal]:
        batch = plan_orders(
            account=account,
            execution_time_nav=decimal("1000000"),
            prices={"HALTED": price, "BUYME": price},
            weight_targets={"BUYME": decimal("1")},
            cash_target=decimal("0"),
            budget=_BUDGET,
            rules=rules,
            tradable=tradable,
        )
        return {request.instrument_id: request.delta_quantity for request in batch.requests}

    halted = plan({"HALTED": False, "BUYME": True})
    assert halted["HALTED"] == decimal("-100"), "the sell is still requested, and still refused"
    assert halted["BUYME"] == decimal("0"), "nothing is bought with money that will not arrive"

    # The same batch with the halt lifted is funded by the sale, which is the point of the netting.
    open_market = plan({"HALTED": True, "BUYME": True})
    assert open_market["HALTED"] == decimal("-100")
    assert open_market["BUYME"] > decimal("99")

    # A caller that knows nothing about halts is unchanged.
    assert plan(None) == open_market


def test_a_fully_invested_batch_is_payable_under_the_accounts_own_arithmetic() -> None:
    """Planning reserves term by term; the account charges fill by fill. Both must agree.

    The two sums are algebraically identical and not identical in ``Decimal``: a notional on a
    real book already uses all 28 significant digits, so the same money summed in a different
    order can differ in the last one. A book that keeps cash absorbs that silently. One that
    declares ``cash_target = 0`` -- which is what an enhanced index holding its ETF sleeve as a
    position declares -- lands within an ulp of zero, and ``prepare_fill`` refuses **any**
    negative, ending the run.

    The values below are the real rebalance that found it: session 8 of a KOSPI 200 enhanced
    index, reduced to the three largest positions, which still reproduces. Without the payability
    settle the projection is ``-2.99E-18``.
    """
    step = decimal("0.000001")
    prices = {
        "A005930": decimal("48200.0000"),
        "A000660": decimal("74400.0000"),
        "K200-TRACKER": decimal("10817.0000"),
    }
    held = {
        "A005930": decimal("534290.4127971083679300140730"),
        "A000660": decimal("109205.0987494961376609962325"),
        "K200-TRACKER": decimal("1842789.116226514734919544650"),
    }
    targets = {
        "A005930": decimal("0.719393548162"),
        "A000660": decimal("0.080606451838"),
        "K200-TRACKER": decimal("0.200000000000"),
    }
    assert sum(targets.values(), Decimal(0)) == 1, "fully invested: no cash to absorb rounding"

    rules = rules_view(
        "v",
        {
            name: TradeRule(
                name,
                step,
                step,
                True,
                ListingAccess.SIGNED,
                SideCost(commission_rate=decimal("0.0003")),
                SideCost(commission_rate=decimal("0.0003"), tax_rate=decimal("0.002")),
            )
            for name in prices
        },
    )
    account = AccountSnapshot(0, decimal("0.000000000000000003516"), held)
    nav = account.cash + sum(
        (quantity * prices[name] for name, quantity in held.items()), Decimal(0)
    )

    batch = plan_orders(
        account=account,
        execution_time_nav=nav,
        prices=prices,
        weight_targets=targets,
        cash_target=decimal("0"),
        budget=_BUDGET,
        rules=rules,
    )

    # Exactly what Account.prepare_fill accumulates, in the order it accumulates it.
    cash = account.cash
    for request in sorted(batch.requests, key=lambda item: item.instrument_id):
        if request.delta_quantity == 0:
            continue
        price = prices[request.instrument_id]
        notional = abs(request.delta_quantity) * price
        side = Side.BUY if request.delta_quantity > 0 else Side.SELL
        cash -= request.delta_quantity * price + rules.charge(
            side, notional, request.instrument_id
        ).total
    assert cash >= 0, f"planned batch overdraws the account by {-cash}"

    # And the shave is one lot, not a retreat. What the book gives up is the cost of trading,
    # not the settle: rotating this much of the account through a 3/23bp band is ~6bp, and the
    # payability shave is a millionth of a share on top of it.
    invested = sum(
        (
            (held.get(request.instrument_id, Decimal(0)) + request.delta_quantity)
            * prices[request.instrument_id]
            for request in batch.requests
        ),
        Decimal(0),
    )
    assert invested / nav > decimal("0.999")
