"""From the four recorded tables to the report's sections -- pure functions of rows.

Takes rows rather than a store or a record, for the reason `analysis/execution.py` gives: a
function of data is testable with a list of dicts and cannot go looking for anything the run did
not record. The door that opens a record and feeds these is `report/record.py`.

The time grid is the `_ACCOUNT` row of `vqapr.account`: one valuation per instant. A period runs
from one valuation to the next, and a fill belongs to the period whose closing valuation's
`account_version` is the first at or above the fill's -- the version is the commit order, which
is exact where a clock comparison across two tables would be a guess.

Every value is a `Decimal`; the fill and weight tables carry theirs as text and are parsed here.
`None` is kept as `None` (a held name with no mark, a refused fill with no price) and never
turned into a zero except where the docstring says a zero is the truth (a refused fill cost
nothing).
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import pairwise

from vqapr.analysis.execution import fill_summary
from vqapr.analysis.performance import drawdown as running_drawdown
from vqapr.analysis.performance import returns as period_returns
from vqapr.analysis.signal import correlation as pearson_correlation
from vqapr.report.document import (
    Attribution,
    Book,
    CalendarRow,
    Compliance,
    ConstraintSummary,
    Correlation,
    Costs,
    HeadlineRow,
    Holding,
    InstrumentPnl,
    Intent,
    OffenderCount,
    Performance,
    Relative,
    Series,
    StrategyReport,
    Trading,
)

ACCOUNT_ROW = "_ACCOUNT"
"""The cash-and-NAV row's `instrument` in `vqapr.account`
(`flow/strategy/context._ACCOUNT_IDENTITY`)."""

ZERO = Decimal(0)
ONE = Decimal(1)
BASIS_POINTS = Decimal(10_000)

Row = Mapping[str, object]


# ---------------------------------------------------------------------------------------------
# Values and the valuation grid
# ---------------------------------------------------------------------------------------------


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _required(value: object, *, name: str, where: str) -> Decimal:
    parsed = _decimal(value)
    if parsed is None:
        raise ValueError(
            f"{name} is null on the {ACCOUNT_ROW} row at {where}; the recorder wrote it"
        )
    return parsed


def _sign(value: Decimal) -> int:
    return (value > 0) - (value < 0)


@dataclass(frozen=True)
class Position:
    quantity: Decimal
    price: Decimal | None

    @property
    def value(self) -> Decimal | None:
        return None if self.price is None else self.quantity * self.price


@dataclass(frozen=True)
class Valuation:
    """One `vqapr.account` instant: the book as it was marked."""

    at: datetime
    version: int
    cash: Decimal
    nav: Decimal
    positions: dict[str, Position]


def valuations(account_rows: Iterable[Row]) -> list[Valuation]:
    """The valuation grid from `vqapr.account`, in time order.

    Rows of one valuation share an `event_time`; the `_ACCOUNT` row carries cash and NAV, and each
    other row one held name. A group without its account row is refused by instant rather than
    read as a valuation of zero, and a non-positive NAV is refused by `returns` downstream.
    """
    heads: dict[datetime, Row] = {}
    members: dict[datetime, dict[str, Position]] = {}
    for row in account_rows:
        at = row["event_time"]
        if not isinstance(at, datetime):
            raise ValueError(f"event_time must be an instant; got {type(at).__name__}")
        instrument = str(row["instrument"])
        if instrument == ACCOUNT_ROW:
            if at in heads:
                raise ValueError(f"two {ACCOUNT_ROW} rows at {at.isoformat()}")
            heads[at] = row
            members.setdefault(at, {})
            continue
        quantity = _decimal(row.get("quantity"))
        if quantity is None:
            raise ValueError(f"quantity is null for {instrument!r} at {at.isoformat()}")
        members.setdefault(at, {})[instrument] = Position(quantity, _decimal(row.get("price")))
    missing = sorted(at for at in members if at not in heads)
    if missing:
        raise ValueError(
            f"{len(missing)} valuation(s) have position rows and no {ACCOUNT_ROW} row; first at "
            f"{missing[0].isoformat()}"
        )
    produced = []
    for at in sorted(heads):
        head = heads[at]
        where = at.isoformat()
        produced.append(
            Valuation(
                at=at,
                version=int(head["account_version"]),  # type: ignore[arg-type]
                cash=_required(head.get("cash"), name="cash", where=where),
                nav=_required(head.get("nav"), name="nav", where=where),
                positions={
                    name: position
                    for name, position in members[at].items()
                    if position.quantity != 0
                },
            )
        )
    return produced


def opening(
    grid: Sequence[Valuation], *, initial_cash: Decimal | None, period_start: datetime | None
) -> list[Valuation]:
    """The grid with the run's initial account in front, when the first valuation already
    reflects a fill (`account_version > 0`) and the initial positions were empty.

    Without it the first day's fills fall before any period -- unattributed, uncounted in
    turnover -- and the first return hides the cost of entering. When the first valuation is
    version 0 it IS the initial book, and the point would be a duplicate.
    """
    if not grid or initial_cash is None or period_start is None or grid[0].version == 0:
        return list(grid)
    if period_start >= grid[0].at:
        raise ValueError(
            f"the run's period starts at {period_start.isoformat()}, not before its first "
            f"valuation at {grid[0].at.isoformat()}"
        )
    first = Valuation(at=period_start, version=0, cash=initial_cash, nav=initial_cash, positions={})
    return [first, *grid]


def infer_periods_per_year(instants: Sequence[datetime]) -> int:
    """From the median spacing of the valuation grid: daily 252, weekly 52, monthly 12,
    quarterly 4, else 1. Reported beside the number it produced, so a reader can override it."""
    if len(instants) < 2:
        return 252
    gaps = sorted(
        (later - earlier).total_seconds() / 86_400 for earlier, later in pairwise(instants)
    )
    typical = gaps[len(gaps) // 2]
    if typical <= 1.6:
        return 252
    if typical <= 8:
        return 52
    if typical <= 32:
        return 12
    if typical <= 100:
        return 4
    return 1


# ---------------------------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------------------------


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    return sum(values, ZERO) / len(values) if values else None


def _std(values: Sequence[Decimal]) -> Decimal | None:
    """Sample standard deviation (ddof=1); `None` below two values."""
    if len(values) < 2:
        return None
    mean = sum(values, ZERO) / len(values)
    return (sum(((v - mean) ** 2 for v in values), ZERO) / (len(values) - 1)).sqrt()


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _share(count: int, total: int) -> Decimal | None:
    return None if total == 0 else Decimal(count) / Decimal(total)


def _pearson(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal | None:
    """`analysis.signal.correlation` with its one refusal read as `None`: a constant series has no
    correlation with anything, and the matrix shows that as a hole rather than a zero. The
    period returns here are finite (NAV is positive), so no-spread is the only `ValueError`
    the shared function can raise on them."""
    if len(left) < 2:
        return None
    try:
        return pearson_correlation(left, right)
    except ValueError:
        return None


def _compounded(values: Sequence[Decimal]) -> Decimal:
    product = ONE
    for value in values:
        product *= ONE + value
    return product - ONE


# ---------------------------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------------------------


def _calendar(
    instants: Sequence[datetime],
    values: Sequence[Decimal],
    *,
    label: str,
    periods_per_year: int,
    risk_free_per_period: Decimal,
) -> CalendarRow:
    annual = Decimal(periods_per_year)
    deviation = _std(values)
    volatility = None if deviation is None else deviation * annual.sqrt()
    excess = [value - risk_free_per_period for value in values]
    local_nav = [ONE]
    for value in values:
        local_nav.append(local_nav[-1] * (ONE + value))
    return CalendarRow(
        label=label,
        periods=len(values),
        total_return=_compounded(values),
        annualized_volatility=volatility,
        sharpe=_ratio(None if not excess else _mean(excess) * annual, volatility),  # type: ignore[operator]
        max_drawdown=min(running_drawdown(local_nav)),
    )


def performance(
    grid: Sequence[Valuation],
    *,
    periods_per_year: int,
    periods_per_year_source: str,
    risk_free_annual: Decimal,
    initial_nav: Decimal | None,
) -> Performance:
    """NAV, return and drawdown of the account row, and the statistics a paper's first table
    carries. Formulas are on `document.Performance`. `initial_nav` is carried into the document
    for the reader; whether it stands as the first point of the grid is `opening`'s decision.
    """
    if not grid:
        raise ValueError("performance needs at least one valuation")
    instants = [valuation.at for valuation in grid]
    nav = [valuation.nav for valuation in grid]
    rets = list(period_returns(nav)) if len(nav) >= 2 else []
    return_instants = instants[1:]
    dd = list(running_drawdown(nav))
    annual = Decimal(periods_per_year)
    count = len(rets)
    total = nav[-1] / nav[0] - ONE
    annualized = (ONE + total) ** (annual / count) - ONE if count else ZERO
    deviation = _std(rets)
    volatility = None if deviation is None else deviation * annual.sqrt()
    risk_free_per_period = risk_free_annual / annual
    excess = [value - risk_free_per_period for value in rets]
    excess_mean = _mean(excess)
    sharpe = _ratio(None if excess_mean is None else excess_mean * annual, volatility)
    downside = (
        None
        if not excess
        else (sum((min(value, ZERO) ** 2 for value in excess), ZERO) / len(excess)).sqrt()
        * annual.sqrt()
    )
    sortino = _ratio(None if excess_mean is None else excess_mean * annual, downside)
    max_dd = min(dd)
    max_dd_at = instants[dd.index(max_dd)] if max_dd < 0 else None
    longest = current = 0
    for value in dd:
        current = current + 1 if value < 0 else 0
        longest = max(longest, current)
    calmar = _ratio(annualized, -max_dd) if max_dd < 0 else None

    by_year: list[CalendarRow] = []
    by_month: list[CalendarRow] = []
    for labelled, sink in (
        (lambda at: str(at.year), by_year),
        (lambda at: f"{at.year}-{at.month:02d}", by_month),
    ):
        buckets: dict[str, tuple[list[datetime], list[Decimal]]] = {}
        for at, value in zip(return_instants, rets, strict=True):
            bucket = buckets.setdefault(labelled(at), ([], []))
            bucket[0].append(at)
            bucket[1].append(value)
        for label, (ats, values) in buckets.items():
            sink.append(
                _calendar(
                    ats,
                    values,
                    label=label,
                    periods_per_year=periods_per_year,
                    risk_free_per_period=risk_free_per_period,
                )
            )

    return Performance(
        periods_per_year=periods_per_year,
        periods_per_year_source=periods_per_year_source,  # type: ignore[arg-type]
        risk_free_annual=risk_free_annual,
        initial_nav=initial_nav,
        nav=Series(instants=instants, values=list(nav)),
        returns=Series(instants=return_instants, values=list(rets)),
        drawdown=Series(instants=instants, values=list(dd)),
        periods=count,
        total_return=total,
        annualized_return=annualized,
        annualized_volatility=volatility,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        max_drawdown=max_dd,
        max_drawdown_at=max_dd_at,
        longest_drawdown_periods=longest,
        positive_period_share=_share(sum(1 for value in rets if value > 0), count),
        by_year=by_year,
        by_month=by_month,
    )


# ---------------------------------------------------------------------------------------------
# The book
# ---------------------------------------------------------------------------------------------


def _weights(valuation: Valuation) -> dict[str, Decimal]:
    if valuation.nav <= 0:
        raise ValueError(f"nav must be positive to define a weight; {valuation.at.isoformat()}")
    return {
        name: position.value / valuation.nav  # type: ignore[operator]
        for name, position in valuation.positions.items()
        if position.price is not None
    }


def book(grid: Sequence[Valuation]) -> Book:
    instants, held, long, short, unmarked = [], [], [], [], []
    gross, net, long_exp, short_exp, cash = [], [], [], [], []
    top, hhi = [], []
    for valuation in grid:
        weights = _weights(valuation)
        magnitudes = sorted((abs(w) for w in weights.values()), reverse=True)
        instants.append(valuation.at)
        held.append(len(valuation.positions))
        long.append(sum(1 for p in valuation.positions.values() if p.quantity > 0))
        short.append(sum(1 for p in valuation.positions.values() if p.quantity < 0))
        unmarked.append(len(valuation.positions) - len(weights))
        gross.append(sum(magnitudes, ZERO))
        net.append(sum(weights.values(), ZERO))
        long_exp.append(sum((w for w in weights.values() if w > 0), ZERO))
        short_exp.append(sum((w for w in weights.values() if w < 0), ZERO))
        cash.append(valuation.cash / valuation.nav)
        top.append(magnitudes[0] if magnitudes else ZERO)
        hhi.append(sum((m * m for m in magnitudes), ZERO))
    return Book(
        instants=instants,
        held=held,
        long=long,
        short=short,
        unmarked=unmarked,
        gross_exposure=gross,
        net_exposure=net,
        long_exposure=long_exp,
        short_exposure=short_exp,
        cash_share=cash,
        max_weight=top,
        hhi=hhi,
    )


# ---------------------------------------------------------------------------------------------
# Fills placed on the grid
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fill:
    instrument: str
    version: int
    kind: str | None
    dealt: Decimal
    price: Decimal | None
    cash_delta: Decimal
    commission: Decimal
    tax: Decimal

    @property
    def notional(self) -> Decimal:
        return ZERO if self.price is None else abs(self.dealt * self.price)


def fills(fill_rows: Iterable[Row]) -> list[Fill]:
    """The fill table as values. A refused fill (null `price`, zero `dealt_quantity`) moved no
    cash and cost nothing, so its nulls read as zero -- the one place a null is a zero here."""
    produced = []
    for row in fill_rows:
        produced.append(
            Fill(
                instrument=str(row["instrument"]),
                version=int(row["account_version"]),  # type: ignore[arg-type]
                kind=None if row.get("kind") is None else str(row["kind"]),
                dealt=_decimal(row.get("dealt_quantity")) or ZERO,
                price=_decimal(row.get("price")),
                cash_delta=_decimal(row.get("cash_delta")) or ZERO,
                commission=_decimal(row.get("commission")) or ZERO,
                tax=_decimal(row.get("tax")) or ZERO,
            )
        )
    return produced


def _by_period(grid: Sequence[Valuation], placed: Sequence[Fill]) -> tuple[list[list[Fill]], int]:
    """Fills grouped by the period that closes on them, and the count no period can hold."""
    versions = [valuation.version for valuation in grid]
    periods: list[list[Fill]] = [[] for _ in range(max(len(grid) - 1, 0))]
    outside = 0
    for fill in placed:
        index = bisect_left(versions, fill.version)
        if index == 0 or index >= len(grid):
            outside += 1
            continue
        periods[index - 1].append(fill)
    return periods, outside


# ---------------------------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------------------------


def attribution(grid: Sequence[Valuation], placed: Sequence[Fill]) -> Attribution:
    """Per-period P&L by name and by side; see `document.Attribution` for the identity."""
    periods, _ = _by_period(grid, placed)
    instants, totals, longs, shorts, residuals = [], [], [], [], []
    per_name: dict[str, dict[str, Decimal | int]] = {}
    scored = positive = 0
    for index, window in enumerate(periods):
        opening, closing = grid[index], grid[index + 1]
        cash_by_name: dict[str, Decimal] = {}
        for fill in window:
            cash_by_name[fill.instrument] = (
                cash_by_name.get(fill.instrument, ZERO) + fill.cash_delta
            )
        names = set(opening.positions) | set(closing.positions) | set(cash_by_name)
        total = long = short = ZERO
        for name in sorted(names):
            start = opening.positions.get(name)
            end = closing.positions.get(name)
            if start is None and end is None and cash_by_name.get(name, ZERO) == 0:
                continue  # a refused fill: never held, moved no cash, nothing to attribute
            start_value = ZERO if start is None else start.value
            end_value = ZERO if end is None else end.value
            if start_value is None or end_value is None:
                continue  # unmarked at one end: its P&L stays in the residual, by name below
            pnl = end_value - start_value + cash_by_name.get(name, ZERO)
            side = (
                _sign(start.quantity)
                if start is not None
                else (_sign(end.quantity) if end is not None else 0)
            )
            tally = per_name.setdefault(name, {"pnl": ZERO, "long": ZERO, "short": ZERO, "held": 0})
            tally["pnl"] += pnl  # type: ignore[operator]
            if side > 0:
                long += pnl
                tally["long"] += pnl  # type: ignore[operator]
            elif side < 0:
                short += pnl
                tally["short"] += pnl  # type: ignore[operator]
            total += pnl
            if start is not None or end is not None:
                scored += 1
                tally["held"] += 1  # type: ignore[operator]
                positive += pnl > 0
        instants.append(closing.at)
        totals.append(total)
        longs.append(long)
        shorts.append(short)
        residuals.append(closing.nav - opening.nav - total)
    by_instrument = sorted(
        (
            InstrumentPnl(
                instrument=name,
                pnl=tally["pnl"],  # type: ignore[arg-type]
                long_pnl=tally["long"],  # type: ignore[arg-type]
                short_pnl=tally["short"],  # type: ignore[arg-type]
                periods_held=tally["held"],  # type: ignore[arg-type]
            )
            for name, tally in per_name.items()
        ),
        key=lambda entry: (-entry.pnl, entry.instrument),
    )
    return Attribution(
        instants=instants,
        total=totals,
        long=longs,
        short=shorts,
        residual=residuals,
        total_pnl=sum(totals, ZERO),
        long_pnl=sum(longs, ZERO),
        short_pnl=sum(shorts, ZERO),
        position_hit_rate=_share(positive, scored),
        by_instrument=by_instrument,
    )


# ---------------------------------------------------------------------------------------------
# Trading
# ---------------------------------------------------------------------------------------------


def decisions(weight_rows: Iterable[Row]) -> list[tuple[datetime, dict[str, Decimal]]]:
    """`vqapr.weight` as one intended book per decision instant, in time order."""
    books: dict[datetime, dict[str, Decimal]] = {}
    for row in weight_rows:
        at = row["event_time"]
        if not isinstance(at, datetime):
            raise ValueError(f"event_time must be an instant; got {type(at).__name__}")
        weight = _decimal(row.get("weight"))
        if weight is None:
            raise ValueError(f"weight is null for {row.get('instrument')!r} at {at.isoformat()}")
        books.setdefault(at, {})[str(row["instrument"])] = weight
    return [(at, books[at]) for at in sorted(books)]


def _holding(grid: Sequence[Valuation]) -> Holding:
    lengths: list[int] = []
    open_runs: dict[str, int] = {}
    for valuation in grid:
        for name in list(open_runs):
            if name in valuation.positions:
                open_runs[name] += 1
            else:
                lengths.append(open_runs.pop(name))
        for name in valuation.positions:
            open_runs.setdefault(name, 1)
    return Holding(
        round_trips=len(lengths),
        mean_periods=_mean([Decimal(length) for length in lengths]),
        open_at_end=len(open_runs),
    )


def trading(
    grid: Sequence[Valuation],
    placed: Sequence[Fill],
    fill_rows: Sequence[Row],
    intended: Sequence[tuple[datetime, dict[str, Decimal]]],
    *,
    periods_per_year: int,
    positions_recorded: bool,
) -> Trading:
    periods, outside = _by_period(grid, placed)
    years = Decimal(len(periods)) / Decimal(periods_per_year) if periods else None
    # One-way, like the intended series: a buy and the sale that funds it are one turn.
    turnover = [
        sum((fill.notional for fill in window), ZERO) / grid[index].nav / 2
        for index, window in enumerate(periods)
    ]
    realized = Series(instants=[v.at for v in grid[1:]], values=list(turnover))
    previous: dict[str, Decimal] = {}
    intended_turnover: list[Decimal] = []
    for _, weights in intended:
        names = set(previous) | set(weights)
        intended_turnover.append(
            sum((abs(weights.get(n, ZERO) - previous.get(n, ZERO)) for n in names), ZERO) / 2
        )
        previous = weights
    commission = sum((fill.commission for fill in placed), ZERO)
    tax = sum((fill.tax for fill in placed), ZERO)
    notional = sum((fill.notional for fill in placed), ZERO)
    by_kind: dict[str, Decimal] = {}
    for fill in placed:
        key = "unknown" if fill.kind is None else fill.kind
        by_kind[key] = by_kind.get(key, ZERO) + fill.commission + fill.tax
    mean_nav = _mean([valuation.nav for valuation in grid])
    costs = Costs(
        commission=commission,
        tax=tax,
        total=commission + tax,
        traded_notional=notional,
        basis_points_of_notional=_ratio((commission + tax) * BASIS_POINTS, notional),
        share_of_mean_nav_per_year=(
            None
            if years is None or mean_nav is None or years == 0
            else (commission + tax) / mean_nav / years
        ),
        by_kind=dict(sorted(by_kind.items())),
    )
    return Trading(
        realized_turnover=realized,
        annualized_realized_turnover=_ratio(sum(turnover, ZERO), years),
        intended_turnover=Series(
            instants=[at for at, _ in intended], values=list(intended_turnover)
        ),
        annualized_intended_turnover=_ratio(sum(intended_turnover, ZERO), years),
        rebalances=len(intended),
        orders_per_rebalance=_ratio(Decimal(len(placed)), Decimal(len(intended))),
        fills_outside_periods=outside,
        fills=fill_summary(fill_rows),
        costs=costs,
        holding=_holding(grid) if positions_recorded else None,
    )


# ---------------------------------------------------------------------------------------------
# Intended against realised
# ---------------------------------------------------------------------------------------------


def intent(
    grid: Sequence[Valuation], intended: Sequence[tuple[datetime, dict[str, Decimal]]]
) -> Intent:
    instants_on_grid = [valuation.at for valuation in grid]
    realized_weights = [_weights(valuation) for valuation in grid]
    instants, realized_at, gaps = [], [], []
    scored = hits = 0
    for at, weights in intended:
        index = bisect_left(instants_on_grid, at)
        if index >= len(grid):
            continue  # decided after the last valuation: nothing realised to compare with
        realized = realized_weights[index]
        names = set(weights) | set(realized)
        instants.append(at)
        realized_at.append(grid[index].at)
        gaps.append(sum((abs(realized.get(n, ZERO) - weights.get(n, ZERO)) for n in names), ZERO))
        if index + 1 < len(grid):
            for name, weight in weights.items():
                start = grid[index].positions.get(name)
                end = grid[index + 1].positions.get(name)
                if weight == 0 or start is None or end is None:
                    continue
                if start.price is None or end.price is None or start.price == 0:
                    continue
                move = end.price / start.price - ONE
                if move == 0:
                    continue
                scored += 1
                hits += _sign(weight) == _sign(move)
    worst = max(gaps) if gaps else None
    return Intent(
        instants=instants,
        realized_at=realized_at,
        gap=gaps,
        mean_gap=_mean(gaps),
        max_gap=worst,
        max_gap_at=None if worst is None else instants[gaps.index(worst)],
        weight_sign_hit_rate=_share(hits, scored),
        weights_scored=scored,
    )


# ---------------------------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------------------------


def compliance(monitoring_rows: Iterable[Row]) -> Compliance:
    counters: dict[str, dict[str, int]] = {}
    worst: dict[str, tuple[Decimal, datetime]] = {}
    offenders: dict[str, dict[str, int]] = {}
    judged: dict[str, bool] = {}
    breached_at: dict[datetime, int] = {}
    for row in monitoring_rows:
        name = str(row["constraint"])
        at = row["event_time"]
        tally = counters.setdefault(
            name, {"checked": 0, "held": 0, "within_tolerance": 0, "breached": 0, "unmeasured": 0}
        )
        tally["checked"] += 1
        breached_at.setdefault(at, 0)  # type: ignore[arg-type]
        verdict = row.get("verdict")
        judged[name] = judged.get(name, True) and verdict is not None
        if row.get("measured") is None:
            tally["unmeasured"] += 1
            continue
        if verdict is None:
            verdict = "held" if bool(row.get("passed")) else "breached"
        verdict = str(verdict)
        if verdict not in ("held", "within_tolerance", "breached"):
            raise ValueError(f"{name}: unknown verdict {verdict!r} at {at}")
        tally[verdict] += 1
        excess = _decimal(row.get("excess"))
        if excess is not None and excess > 0 and (name not in worst or excess > worst[name][0]):
            worst[name] = (excess, at)  # type: ignore[assignment]
        if verdict == "breached":
            breached_at[at] += 1  # type: ignore[index]
            for instrument in str(row.get("offenders") or "").split():
                bucket = offenders.setdefault(name, {})
                bucket[instrument] = bucket.get(instrument, 0) + 1
    summaries = [
        ConstraintSummary(
            constraint=name,
            checked=tally["checked"],
            held=tally["held"],
            within_tolerance=tally["within_tolerance"],
            breached=tally["breached"],
            unmeasured=tally["unmeasured"],
            breach_share=_share(tally["breached"], tally["checked"]),
            worst_excess=worst[name][0] if name in worst else None,
            worst_excess_at=worst[name][1] if name in worst else None,
            offenders=[
                OffenderCount(instrument=instrument, findings=count)
                for instrument, count in sorted(
                    offenders.get(name, {}).items(), key=lambda item: (-item[1], item[0])
                )
            ],
            tolerance_judged=judged[name],
        )
        for name, tally in sorted(counters.items())
    ]
    instants = sorted(breached_at)
    return Compliance(
        constraints=summaries, instants=instants, breached=[breached_at[at] for at in instants]
    )


# ---------------------------------------------------------------------------------------------
# Across the strategies of one run
# ---------------------------------------------------------------------------------------------


def headline(report: StrategyReport) -> HeadlineRow:
    return HeadlineRow(
        strategy_ref=report.strategy_ref,
        strategy_id=report.strategy_id,
        periods=report.performance.periods,
        total_return=report.performance.total_return,
        annualized_return=report.performance.annualized_return,
        annualized_volatility=report.performance.annualized_volatility,
        sharpe=report.performance.sharpe,
        max_drawdown=report.performance.max_drawdown,
        annualized_realized_turnover=report.trading.annualized_realized_turnover,
        cost_share_of_mean_nav_per_year=report.trading.costs.share_of_mean_nav_per_year,
        breached=(
            None
            if report.compliance is None
            else sum(entry.breached for entry in report.compliance.constraints)
        ),
    )


def _aligned(reports: Sequence[StrategyReport]) -> tuple[list[datetime], list[list[Decimal]]]:
    """Period returns on the instants every report shares, in the same order."""
    shared: set[datetime] | None = None
    for report in reports:
        instants = set(report.performance.returns.instants)
        shared = instants if shared is None else shared & instants
    instants = sorted(shared or ())
    columns = []
    for report in reports:
        lookup = dict(
            zip(report.performance.returns.instants, report.performance.returns.values, strict=True)
        )
        columns.append([lookup[at] for at in instants])  # type: ignore[misc]
    return instants, columns


def correlation(reports: Sequence[StrategyReport]) -> Correlation | None:
    if len(reports) < 2:
        return None
    instants, columns = _aligned(reports)
    if len(instants) < 3:
        return None
    # The diagonal is not set by hand: the shared correlation is exactly 1 for a series against
    # itself, and a constant series is `None` there as everywhere else in its row.
    values = [
        [_pearson(columns[i], columns[j]) for j in range(len(reports))] for i in range(len(reports))
    ]
    return Correlation(
        refs=[report.strategy_ref for report in reports], periods=len(instants), values=values
    )


def relative(report: StrategyReport, benchmark: StrategyReport) -> Relative:
    instants, (own, bench) = _aligned([report, benchmark])
    active = [a - b for a, b in zip(own, bench, strict=True)]
    annual = Decimal(report.performance.periods_per_year)
    mean = _mean(active)
    deviation = _std(active)
    tracking = None if deviation is None else deviation * annual.sqrt()
    annualized = ZERO if mean is None else mean * annual
    return Relative(
        strategy_ref=report.strategy_ref,
        benchmark_ref=benchmark.strategy_ref,
        periods=len(instants),
        active_return=Series(instants=instants, values=list(active)),
        tracking_error=tracking,
        information_ratio=_ratio(annualized, tracking),
    )
