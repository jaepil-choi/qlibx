"""What a run's orders actually did, counted from the rows it recorded.

**Moved out of `cli/run.py` by record `114`.** `_fill_summary` was added there under time pressure
in the 0.2.0a2 batch and acknowledged as misplaced. It is not a rendering concern: it is an
aggregate over fill rows, and it is the aggregate `docs/issues/archive/039` shows nobody could
compute by hand in time.

Takes rows rather than a `SimulationResult`, deliberately. That keeps it a pure function of data --
testable with a list of dicts, no run, no flow types, and no inversion of the kind record `113` had
to undo in `evidence/records.py`.

**Any iterable, walked once** (record `254`). `vqapr run` handed it `tuple(read_typed_table(...))`
-- every fill row of the run as a Python dict at once, after the run had ended -- and that was the
peak of a daily 309-name run: about 1.7 KB a fill, 0.8 GB at 460k fills, on top of everything the
run still held
(`docs/issues/report-2026-09-11-a-strategy-runs-memory-grows-with-its-orders-...`). The reader
streams a record table a batch at a time, so the tally below now holds one batch and the counts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal


def fill_summary(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """What this run's orders actually did, which `ok: true` says nothing about.

    `docs/issues/archive/039`. A market-neutral run reported `{"ok": true, "occurrences": 732,
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
