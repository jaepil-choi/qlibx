"""AC-13 of the two-clocks campaign: the wiring table is the architecture, and it is closed.

Design §4: a role is one row -- which clock it is called on, what it is handed, who receives its
answer -- and the two things that differ between roles are decided there and nowhere else. §4.3:
a part declares its own clock, a tool attaches to another's. What is pinned here is that adding a
role means adding a row, that every authored class points at the row it implements, and that the
loop calls the market-clock roles in the order the table says.
"""

from __future__ import annotations

import inspect

from vqapr.authoring import Compliance, Component, DataModel, Part, StrategyModel, Tool
from vqapr.component.exchange.base import Exchange
from vqapr.domain.wiring import (
    EXTENSION_POINTS,
    MARKET_CLOCK_ORDER,
    WIRING,
    Clock,
    Receiver,
    Role,
    View,
    parts,
    roles_on,
    tools,
)
from vqapr.run.engine.loop import MarketClock


def test_every_role_has_exactly_one_row_and_no_row_is_without_a_role() -> None:
    """Adding a `Role` without a row -- or a row without a role -- fails here, which is the
    point: a row decides a clock and a receiver, and those are the framework's decisions."""
    assert set(WIRING) == set(Role)
    assert all(WIRING[role].role is role for role in Role)
    assert list(WIRING) == list(Role), "table order is the design's order"


def test_the_table_is_the_design_paragraph() -> None:
    """Design §4, row by row."""
    assert WIRING[Role.DATA_MODEL].clock is Clock.SCHEDULE
    assert WIRING[Role.DATA_MODEL].receives == (View.WINDOW,)
    assert WIRING[Role.DATA_MODEL].answers_to is Receiver.WAREHOUSE

    assert WIRING[Role.STRATEGY_MODEL].clock is Clock.SCHEDULE
    assert WIRING[Role.STRATEGY_MODEL].receives == (View.WINDOW, View.ACCOUNT, View.HISTORY)
    assert WIRING[Role.STRATEGY_MODEL].answers_to is Receiver.EXCHANGE

    assert WIRING[Role.ACCRUAL].clock is Clock.MARKET
    assert WIRING[Role.ACCRUAL].receives == (View.HOLDINGS, View.WINDOW)
    assert WIRING[Role.ACCRUAL].answers_to is Receiver.LEDGER

    assert WIRING[Role.EXCHANGE].clock is Clock.MARKET
    assert WIRING[Role.EXCHANGE].receives == (
        View.ORDERS, View.MARKET_STATE, View.ACCOUNT, View.INSTRUMENTS
    )
    assert WIRING[Role.EXCHANGE].answers_to is Receiver.LEDGER

    assert WIRING[Role.COMPLIANCE].clock is Clock.MARKET
    assert WIRING[Role.COMPLIANCE].receives == (View.WINDOW, View.COMMITTED_ACCOUNT)
    assert WIRING[Role.COMPLIANCE].answers_to is Receiver.EVIDENCE


def test_a_part_declares_its_clock_and_a_tool_borrows_one() -> None:
    """§4.3: the one criterion. A part is a tool plus a clock; the types say so."""
    assert parts() == (Role.DATA_MODEL, Role.STRATEGY_MODEL)
    assert tools() == (Role.ACCRUAL, Role.EXCHANGE, Role.COMPLIANCE)
    assert roles_on(Clock.SCHEDULE) == parts(), "the schedule clock is the parts' own"
    assert roles_on(Clock.MARKET) == tools(), "every tool attaches to the market clock today"

    assert issubclass(Part, Component) and issubclass(Tool, Component)
    assert not issubclass(Part, Tool) and not issubclass(Tool, Part)
    for role_class in (DataModel, StrategyModel):
        assert issubclass(role_class, Part), role_class
        assert role_class.wiring().is_part
    for role_class in (Exchange, Compliance):
        assert issubclass(role_class, Tool), role_class
        assert role_class.wiring().is_tool


def test_every_authored_class_points_at_the_row_it_implements() -> None:
    by_role = {DataModel.ROLE: DataModel, StrategyModel.ROLE: StrategyModel,
               Exchange.ROLE: Exchange, Compliance.ROLE: Compliance}
    assert set(by_role) == set(Role) - {Role.ACCRUAL}, "Accrual is a row with no class: a place"
    for role, role_class in by_role.items():
        assert role_class.wiring() is WIRING[role]


def test_every_extension_point_is_a_row_and_accrual_is_not_yet_one() -> None:
    """Four doors, five rows (design §8: 넷 + Accrual 자리), named by one enum since record `272`."""
    assert set(EXTENSION_POINTS) == set(Role) - {Role.ACCRUAL}
    assert len(EXTENSION_POINTS) == len(set(EXTENSION_POINTS))


def test_the_loop_calls_the_market_clock_roles_in_the_tables_order() -> None:
    """The order §3.1 fixes, written once as calls in `MarketClock.at`, and once as data here."""
    assert MARKET_CLOCK_ORDER == (Role.ACCRUAL, Role.EXCHANGE, Role.COMPLIANCE)
    assert set(MARKET_CLOCK_ORDER) == set(roles_on(Clock.MARKET))
    source = inspect.getsource(MarketClock.at)
    handlers = {
        Role.ACCRUAL: "._accrual.",
        Role.EXCHANGE: "._execution.fill(",
        Role.COMPLIANCE: "._compliance.",
    }
    positions = [source.index(handlers[role]) for role in MARKET_CLOCK_ORDER]
    assert positions == sorted(positions), "the loop and the table disagree about the order"
