"""The wiring table: which clock each role is called on, what it is handed, who receives its answer.

Design §4 (`docs/design/two-clocks-and-the-wiring-table.md`): **this table is the architecture.**
Every role the framework calls back is one row of it, and the two things that differ between
roles -- when it is called, and who receives its answer -- are decided here and nowhere else
(§4.1). The base class stays thin (§4.2: a role subscribes, remembers, and has one callback); the
clock and the receiver are not on the base, they are on this row.

**The table is the framework's and it is closed.** Adding a role means adding a row, because a
row decides a clock and a receiver, and those are the framework's decisions (§4). The test that
guards this (`tests/domain/test_the_wiring_table.py`) refuses a `Role` without a row and a row
that disagrees with the authoring class that implements it.

**Parts and tools** (§4.3): the one criterion is whether a role declares its own clock. A part
does -- one per run: `DataModel`, `StrategyModel`. A tool attaches to somebody else's clock:
`Exchange`, `Compliance`, `Accrual`. A part is a tool plus a clock, and the types say so
(`authoring.Part`, `authoring.Tool`).

Data rather than types (design §10.2, decided at M13, record `213`): a row is read by tests, by
the loop's docstrings and by a reader of the design; it is compared, listed and counted, which a
table does and a class hierarchy makes you reconstruct. The types carry the one structural fact
that code has to enforce -- part or tool -- and point back here for the rest.

Layer 0: this imports nothing and everything above may read it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

__all__ = [
    "MARKET_CLOCK_ORDER",
    "WIRING",
    "Clock",
    "Receiver",
    "Role",
    "View",
    "Wiring",
    "parts",
    "roles_on",
    "tools",
]


class Role(StrEnum):
    """The five rows of the table. Four are extension points; `ACCRUAL` is a place (§7.3)."""

    DATA_MODEL = "data_model"
    STRATEGY_MODEL = "strategy_model"
    ACCRUAL = "accrual"
    EXCHANGE = "exchange"
    COMPLIANCE = "compliance"


class Clock(StrEnum):
    """The two clocks of a run (design §3): the strategy's own agenda, and the market's instants
    -- every instant the execution table has inside the run."""

    STRATEGY = "strategy"
    MARKET = "market"


class View(StrEnum):
    """What a role is handed, named as the design names it (§4)."""

    WINDOW = "window"
    ACCOUNT = "account"
    HISTORY = "history"
    HOLDINGS = "holdings"
    ORDERS = "orders"
    MARKET_STATE = "market_state"
    INSTRUMENTS = "instruments"
    COMMITTED_ACCOUNT = "committed_account"


class Receiver(StrEnum):
    """Who receives a role's answer (§4). Three are destinations (§5: the warehouse, the
    ledger, the notice board); the exchange is the one intermediate -- a strategy's orders go to
    it, and its fills go to the ledger."""

    WAREHOUSE = "warehouse"
    EXCHANGE = "exchange"
    LEDGER = "ledger"
    EVIDENCE = "evidence"


@dataclass(frozen=True, slots=True)
class Wiring:
    """One row: the role, its clock, what it is handed, who receives its answer, and whether the
    clock is its own (a part) or borrowed (a tool)."""

    role: Role
    clock: Clock
    receives: tuple[View, ...]
    answers_to: Receiver
    declares_clock: bool

    @property
    def is_part(self) -> bool:
        return self.declares_clock

    @property
    def is_tool(self) -> bool:
        return not self.declares_clock


WIRING: Mapping[Role, Wiring] = MappingProxyType(
    {
        Role.DATA_MODEL: Wiring(
            Role.DATA_MODEL, Clock.STRATEGY, (View.WINDOW,), Receiver.WAREHOUSE, True
        ),
        Role.STRATEGY_MODEL: Wiring(
            Role.STRATEGY_MODEL,
            Clock.STRATEGY,
            (View.WINDOW, View.ACCOUNT, View.HISTORY),
            Receiver.EXCHANGE,
            True,
        ),
        Role.ACCRUAL: Wiring(
            Role.ACCRUAL, Clock.MARKET, (View.HOLDINGS, View.WINDOW), Receiver.LEDGER, False
        ),
        Role.EXCHANGE: Wiring(
            Role.EXCHANGE,
            Clock.MARKET,
            (View.ORDERS, View.MARKET_STATE, View.ACCOUNT, View.INSTRUMENTS),
            Receiver.LEDGER,
            False,
        ),
        Role.COMPLIANCE: Wiring(
            Role.COMPLIANCE,
            Clock.MARKET,
            (View.WINDOW, View.COMMITTED_ACCOUNT),
            Receiver.EVIDENCE,
            False,
        ),
    }
)
"""Design §4, verbatim:

    역할            시계        받는 View                         답의 수신자
    DataModel       전략 시계   창                                 창고
    StrategyModel   전략 시계   창 + 계좌 + 이력                   주문 → Exchange
    Accrual         시장 시계   보유 + 창                          통장       (자리만, §7.3)
    Exchange        시장 시계   주문 + 시장상태 + 계좌 + 종목사전   통장
    Compliance      시장 시계   창 + committed 계좌                게시판
"""

MARKET_CLOCK_ORDER: tuple[Role, ...] = (Role.ACCRUAL, Role.EXCHANGE, Role.COMPLIANCE)
"""The roles a market-clock instant calls, in the order §3.1 fixes: ACCRUE, EXECUTE, then --
after the framework's own VALUATION -- COMPLIANCE. A decision (DECIDE) is the strategy clock's,
sorted after the market instant it coincides with. `StrategyEventLoop._handle_market` is the one
place this order is written as calls, and the wiring test holds the two together."""


def roles_on(clock: Clock) -> tuple[Role, ...]:
    """The roles called on `clock`, in table order."""
    return tuple(role for role, wiring in WIRING.items() if wiring.clock is clock)


def parts() -> tuple[Role, ...]:
    """The roles that declare their own clock -- one per run."""
    return tuple(role for role, wiring in WIRING.items() if wiring.is_part)


def tools() -> tuple[Role, ...]:
    """The roles that attach to another's clock."""
    return tuple(role for role, wiring in WIRING.items() if wiring.is_tool)
