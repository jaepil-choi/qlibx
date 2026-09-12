"""The report documents: one per strategy, one per run.

Every number here is a `Decimal`, because every number in the record is one (or text that was
one), and a report that re-derived them in floating point would be the second, unreconciled
performance number `report/metrics.py` exists to keep out. `as_record()` serialises a
`Decimal` as text and an instant as ISO 8601 with its offset, so a reader in any language gets
the exact value and the right zone.

A section that cannot be computed from what the run recorded is `None`, and
`StrategyReport.omitted` says why by name. A run that recorded only the account row (`vqapr run
--no-account-positions`) has a NAV series and no book; the report says so rather than showing a
book of zero names.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "Attribution",
    "Book",
    "CalendarRow",
    "Compliance",
    "ComplianceSummary",
    "Correlation",
    "Costs",
    "Curve",
    "HeadlineRow",
    "Holding",
    "InstrumentPnl",
    "Intent",
    "OffenderCount",
    "Performance",
    "Relative",
    "RunReport",
    "StrategyReport",
    "Trading",
]


class _Document(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def as_record(self) -> dict[str, Any]:
        """JSON-ready: `Decimal` as text (exact), instants as ISO 8601 with offset."""
        return self.model_dump(mode="json")


class Curve(_Document):
    """Instants beside values, same length. A `None` value is a point the record could not
    value (a held name with no mark), never a zero."""

    instants: list[datetime]
    values: list[Decimal | None]


class CalendarRow(_Document):
    """One calendar bucket of the return series: a year or a month, labelled by the instants'
    own zone."""

    label: str
    periods: int
    total_return: Decimal
    annualized_volatility: Decimal | None
    sharpe: Decimal | None
    max_drawdown: Decimal


class Performance(_Document):
    """NAV, return and drawdown from the `_ACCOUNT` row of `vqapr.account`, one point per
    valuation.

    `annualized_return` is geometric (`(1 + total) ** (periods_per_year / periods) - 1`);
    `sharpe` is arithmetic (`(mean - rf_per_period) * periods_per_year / annualized_volatility`),
    so the two do not share a numerator and a reader should not expect them to. `sortino`
    replaces the denominator with the downside deviation (root mean square of the negative excess
    returns, over ALL periods). `calmar` is the geometric annualized return over `|max_drawdown|`.
    `risk_free_annual` is what the caller gave; the record holds no rate, so the default is zero
    and the report says so rather than guessing one.
    """

    periods_per_year: int
    periods_per_year_source: Literal["given", "inferred"]
    risk_free_annual: Decimal
    initial_nav: Decimal | None
    nav: Curve
    returns: Curve
    drawdown: Curve
    periods: int
    total_return: Decimal
    annualized_return: Decimal
    annualized_volatility: Decimal | None
    sharpe: Decimal | None
    sortino: Decimal | None
    calmar: Decimal | None
    max_drawdown: Decimal
    max_drawdown_at: datetime | None
    longest_drawdown_periods: int
    positive_period_share: Decimal | None
    by_year: list[CalendarRow]
    by_month: list[CalendarRow]


class Book(_Document):
    """The realised book at each valuation: `quantity * price / nav` per held name.

    Exposures are shares of NAV: `gross` is the sum of absolute weights, `net` the signed sum,
    `long` and `short` the two sides (`short` is non-positive). `hhi` is the sum of squared
    absolute weights (1 = one name). A held name with no mark at that valuation is counted in
    `held` but contributes nothing to the exposures, and `unmarked` says how many.
    """

    instants: list[datetime]
    held: list[int]
    long: list[int]
    short: list[int]
    unmarked: list[int]
    gross_exposure: list[Decimal]
    net_exposure: list[Decimal]
    long_exposure: list[Decimal]
    short_exposure: list[Decimal]
    cash_share: list[Decimal]
    max_weight: list[Decimal]
    hhi: list[Decimal]


class InstrumentPnl(_Document):
    instrument: str
    pnl: Decimal
    long_pnl: Decimal
    short_pnl: Decimal
    periods_held: int


class Attribution(_Document):
    """Profit and loss per period, by name and by side, from positions and fills.

    For each period between two valuations, a name's P&L is its marked value at the end minus
    its marked value at the start plus the `cash_delta` of every fill committed in between
    (negative on a buy, so a purchase is not a gain). Summed over names this equals the change in
    NAV exactly, and `residual` is the difference the record shows -- non-zero only where a held
    name had no mark or cash moved without a fill. It is reported, not absorbed.

    A period's P&L on a name is `long` when the name was held long at the period's start (or
    opened long in it) and `short` when held short; a name that flips sign within one period is
    assigned by its opening side. `position_hit_rate` is the share of (name, period) pairs with a
    positive P&L among those where the name was held.
    """

    instants: list[datetime]
    total: list[Decimal]
    long: list[Decimal]
    short: list[Decimal]
    residual: list[Decimal]
    total_pnl: Decimal
    long_pnl: Decimal
    short_pnl: Decimal
    position_hit_rate: Decimal | None
    by_instrument: list[InstrumentPnl]


class Costs(_Document):
    """What trading cost, summed over `vqapr.fill` -- per fill and per side, never a rate times a
    turnover estimate. `by_kind` splits the total by the roster category the fill carried
    (`None` kind is the key `"unknown"`). A refused fill carries no cost and counts as zero."""

    commission: Decimal
    tax: Decimal
    total: Decimal
    traded_notional: Decimal
    basis_points_of_notional: Decimal | None
    share_of_mean_nav_per_year: Decimal | None
    by_kind: dict[str, Decimal]


class Holding(_Document):
    """How long a name stays in the book, in valuation periods: a round trip is a run of
    consecutive valuations with a non-zero quantity, closed when the quantity returns to zero."""

    round_trips: int
    mean_periods: Decimal | None
    open_at_end: int


class Trading(_Document):
    """Turnover, costs and what the orders did.

    `realized_turnover` is `sum |dealt * price| / (2 * nav)` per period, with the NAV at the
    period's start; `intended_turnover` is `sum |w - w_previous| / 2` per decision, from
    `vqapr.weight`. Both are one-way, so they compare.
    The two annualised numbers beside each other are the size of what did not execute. `fills`
    is `vqapr.report.metrics.fill_summary` over the fill table, unchanged.
    `fills_outside_periods` counts fills committed before the first valuation or after the last,
    which the per-period series cannot place.
    """

    realized_turnover: Curve
    annualized_realized_turnover: Decimal | None
    intended_turnover: Curve
    annualized_intended_turnover: Decimal | None
    rebalances: int
    orders_per_rebalance: Decimal | None
    fills_outside_periods: int
    fills: dict[str, Any]
    costs: Costs
    holding: Holding | None


class Intent(_Document):
    """Intended against realised (PRD §9.4): each decision's `vqapr.weight` against the book at
    the first valuation at or after it. `gap` is `sum |realised - intended|` over the names
    either side names. `weight_sign_hit_rate` is the share of intended weights whose sign matched
    the name's price return over the period that followed that valuation, among names the record
    marked at both ends."""

    instants: list[datetime]
    realized_at: list[datetime]
    gap: list[Decimal]
    mean_gap: Decimal | None
    max_gap: Decimal | None
    max_gap_at: datetime | None
    weight_sign_hit_rate: Decimal | None
    weights_scored: int


class OffenderCount(_Document):
    instrument: str
    findings: int


class ComplianceSummary(_Document):
    """One declared Compliance rule over the run, from `vqapr.monitoring`. `checked` splits into
    `held`, `within_tolerance`, `breached` and `unmeasured` (a finding with no `measured` value:
    an input the rule could not see, which is not a breach). A record written before the
    framework's verdict existed (record `158`) has only the author's `passed`; then `held` and
    `breached` follow it and `tolerance_judged` is false."""

    rule: str
    checked: int
    held: int
    within_tolerance: int
    breached: int
    unmeasured: int
    breach_share: Decimal | None
    worst_excess: Decimal | None
    worst_excess_at: datetime | None
    offenders: list[OffenderCount]
    tolerance_judged: bool


class Compliance(_Document):
    rules: list[ComplianceSummary]
    instants: list[datetime]
    breached: list[int]


class StrategyReport(_Document):
    run_id: str
    strategy_ref: str
    strategy_id: str
    period: dict[str, Any]
    positions_recorded: bool
    omitted: dict[str, str]
    performance: Performance
    book: Book | None
    attribution: Attribution | None
    trading: Trading
    intent: Intent | None
    compliance: Compliance | None


class HeadlineRow(_Document):
    """One line of the table a paper puts first: one strategy of the run."""

    strategy_ref: str
    strategy_id: str
    periods: int
    total_return: Decimal
    annualized_return: Decimal
    annualized_volatility: Decimal | None
    sharpe: Decimal | None
    max_drawdown: Decimal
    annualized_realized_turnover: Decimal | None
    cost_share_of_mean_nav_per_year: Decimal | None
    breached: int | None


class Relative(_Document):
    """One strategy against a benchmark strategy of the same run, on the valuations both share:
    the arithmetic difference of period returns, its annualised mean and standard deviation
    (`tracking_error`) and their ratio (`information_ratio`)."""

    strategy_ref: str
    benchmark_ref: str
    periods: int
    active_return: Curve
    tracking_error: Decimal | None
    information_ratio: Decimal | None


class Correlation(_Document):
    """Pearson correlation of period returns between the run's strategies, on the valuations
    every one of them shares, by `vqapr.signals.evaluation.correlation` -- exactly 1 on the diagonal
    and between identical series. `values[i][j]` is `None` when either series is constant."""

    refs: list[str]
    periods: int
    values: list[list[Decimal | None]]


class RunReport(_Document):
    run_id: str
    strategies: dict[str, StrategyReport]
    headline: list[HeadlineRow]
    correlation: Correlation | None
    relative: list[Relative]
