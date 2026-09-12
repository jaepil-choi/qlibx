"""The numbers a report computes from what a run stored: NAV, returns, drawdown, and the fill
summary.

Pure functions over evaluated records. `nav_series` takes the marks a run committed and the
cash beside them; `returns` and `drawdown` take that NAV; `fill_summary` takes the fill rows.
None of them builds a portfolio or re-prices a book -- a number the ledger does not hold
cannot appear in a report. Until record `275` these were `report/metrics.py` and
`report/metrics.py`, a package whose only readers were the report and the surfaces.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal

from vqapr.domain.account import MarkBatch

__all__ = [
    "drawdown",
    "fill_summary",
    "nav_series",
    "returns",
]


def _checked(marks: Sequence[MarkBatch], name: str) -> tuple[MarkBatch, ...]:
    if isinstance(marks, (str, bytes)) or not isinstance(marks, Sequence):
        raise TypeError(f"{name} takes a sequence of MarkBatch")
    if not marks:
        raise ValueError(f"{name} needs at least one mark")
    for index, batch in enumerate(marks):
        if not isinstance(batch, MarkBatch):
            # The refusal names what arrived, because the mistake this guards against is handing
            # in a price panel and getting a plausible-looking number the ledger never agreed to.
            raise TypeError(
                f"{name}[{index}] must be a MarkBatch produced by the valuation spine; "
                f"got {type(batch).__name__}"
            )
    return tuple(marks)


def nav_series(marks: Sequence[MarkBatch], *, cash: Sequence[Decimal]) -> tuple[Decimal, ...]:
    """Net asset value at each mark: marked position value plus the cash held alongside it.

    Cash arrives as an argument rather than being inferred, because the Account owns it and this
    module reads rather than reconstructs.
    """
    checked = _checked(marks, "nav_series")
    if isinstance(cash, (str, bytes)) or not isinstance(cash, Sequence):
        raise TypeError("cash must be a sequence of Decimal")
    if len(cash) != len(checked):
        raise ValueError(
            f"cash has {len(cash)} entries for {len(checked)} marks; they must correspond"
        )
    for index, amount in enumerate(cash):
        if not isinstance(amount, Decimal):
            raise TypeError(f"cash[{index}] must be a Decimal; got {type(amount).__name__}")
        if not amount.is_finite():
            raise ValueError(f"cash[{index}] must be finite")
    return tuple(batch.total_value + amount for batch, amount in zip(checked, cash, strict=True))


def returns(nav: Sequence[Decimal]) -> tuple[Decimal, ...]:
    """Period returns from a NAV series, one fewer than the NAV values.

    A zero or negative starting value is refused rather than skipped: a return is undefined there,
    and skipping it would silently shorten the series a caller is about to compare against dates.
    """
    if isinstance(nav, (str, bytes)) or not isinstance(nav, Sequence):
        raise TypeError("nav must be a sequence of Decimal")
    if len(nav) < 2:
        raise ValueError("returns needs at least two NAV values")
    for index, value in enumerate(nav):
        if not isinstance(value, Decimal):
            raise TypeError(f"nav[{index}] must be a Decimal; got {type(value).__name__}")
        if not value.is_finite():
            raise ValueError(f"nav[{index}] must be finite")
    produced: list[Decimal] = []
    for index in range(1, len(nav)):
        previous = nav[index - 1]
        if previous <= 0:
            raise ValueError(f"nav[{index - 1}] must be positive to define a return")
        produced.append(nav[index] / previous - 1)
    return tuple(produced)


def drawdown(nav: Sequence[Decimal]) -> tuple[Decimal, ...]:
    """Shortfall from the highest value seen so far, at each point, as a non-positive fraction.

    Running peak rather than final peak, because a drawdown is what an investor was living through
    at the time, not what it looks like once the recovery is known.
    """
    if isinstance(nav, (str, bytes)) or not isinstance(nav, Sequence):
        raise TypeError("nav must be a sequence of Decimal")
    if not nav:
        raise ValueError("drawdown needs at least one NAV value")
    for index, value in enumerate(nav):
        if not isinstance(value, Decimal):
            raise TypeError(f"nav[{index}] must be a Decimal; got {type(value).__name__}")
        if not value.is_finite():
            raise ValueError(f"nav[{index}] must be finite")
        if value <= 0:
            raise ValueError(f"nav[{index}] must be positive to define a drawdown")
    produced: list[Decimal] = []
    peak = nav[0]
    for value in nav:
        peak = max(peak, value)
        produced.append(value / peak - 1)
    return tuple(produced)


def fill_summary(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """What this run's orders actually did, which `ok: true` says nothing about.

    `docs/issues/archive/039`. A market-neutral run reported `{"ok": true, "events": 732,
    "account_version": 244}`. Its long side landed on 0.500 every time and its short side never
    did, drifting to **9.1% of NAV in unintended net long exposure** by December -- because 3.1% of
    fills dealt nothing, mostly names that were not tradable at the fill instant.

    The behaviour was right and correctly labelled: every one of those fills carries a
    `ZeroDealtReason` in `vqapr.fill`. **Nothing aggregated them**, so the one signal that would
    have exposed the cause -- a 3.1% zero-dealt rate against a 1.2% baseline -- was reachable only
    by reading 47,318 rows by hand. The reporter found it by accident two hours later.

    So this counts what the run already wrote. `partial` is here for the same reason `zero_dealt`
    is: an order filled short of its request is the same declared-versus-realised gap, one degree
    quieter, and it was 1,404 of that run's short requests.

    Reported on the SUCCESS path deliberately. The run is legitimate; what is worth saying is what
    it managed to trade.
    """
    orders = 0
    dealt = 0
    partial = 0
    zero_dealt = 0
    reasons: dict[str, int] = {}
    per_instrument: dict[str, _PerInstrument] = {}
    for row in rows:
        orders += 1
        instrument = str(row.get("instrument"))
        tally = per_instrument.setdefault(instrument, _PerInstrument())
        tally.orders += 1
        reason = row.get("reason")
        if reason is not None:
            zero_dealt += 1
            reasons[str(reason)] = reasons.get(str(reason), 0) + 1
            tally.reasons[str(reason)] = tally.reasons.get(str(reason), 0) + 1
            continue
        dealt += 1
        tally.dealt += 1
        requested = abs(Decimal(str(row.get("requested_quantity") or "0")))
        filled = abs(Decimal(str(row.get("dealt_quantity") or "0")))
        if filled < requested:
            partial += 1
    # The axis `reasons` cannot see (`docs/issues/archive/085`): one row missing on each of 200
    # names is what a market looks like, the same name missing on every one of 82 rebalances is a
    # configuration error, and both fold into one `absent: N`. A name ordered in a run that never
    # dealt once cannot be produced by ordinary market behaviour at any length of run, so it is
    # stated by instrument, on the success path -- nothing failed. Most-ordered first, so the
    # heaviest sleeve is the first line.
    never_filled = [
        {
            "instrument": instrument,
            "orders": tally.orders,
            "dealt": 0,
            "reason": max(sorted(tally.reasons), key=lambda key: tally.reasons[key]),
        }
        for instrument, tally in per_instrument.items()
        if tally.orders and not tally.dealt
    ]
    never_filled.sort(key=lambda entry: (-int(entry["orders"]), str(entry["instrument"])))
    return {
        # Every order the venue answered, so the three counts below are readable as shares of it.
        "orders": orders,
        "dealt": dealt,
        "partial": partial,
        "zero_dealt": zero_dealt,
        # Named reasons rather than a total, because they are not one fact: `absent`,
        # `nontradable` and `no_trade` are facts about the MARKET, and `unfunded` is a fact about
        # the account. A reader asking what the market refused them must not be handed their own
        # empty purse in the same number.
        "reasons": dict(sorted(reasons.items())),
        "never_filled": never_filled,
    }


class _PerInstrument:
    """One instrument's tally across the run: how often ordered, how often dealt, why not."""

    __slots__ = ("dealt", "orders", "reasons")

    def __init__(self) -> None:
        self.orders = 0
        self.dealt = 0
        self.reasons: dict[str, int] = {}
