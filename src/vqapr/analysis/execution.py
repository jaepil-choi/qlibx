"""What a run's orders actually did, counted from the rows it recorded.

**Moved out of `cli/run.py` by record `114`.** `_fill_summary` was added there under time pressure
in the 0.2.0a2 batch and acknowledged as misplaced. It is not a rendering concern: it is an
aggregate over fill rows, and it is the aggregate `docs/issues/039` shows nobody could compute by
hand in time.

Takes rows rather than a `SimulationResult`, deliberately. That keeps it a pure function of data --
testable with a list of dicts, no run, no flow types, and no inversion of the kind record `113` had
to undo in `evidence/records.py`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal


def fill_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """What this run's orders actually did, which `ok: true` says nothing about.

    `docs/issues/039`. A market-neutral run reported `{"ok": true, "occurrences": 732,
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
    dealt = 0
    partial = 0
    zero_dealt = 0
    reasons: dict[str, int] = {}
    for row in rows:
        reason = row.get("reason")
        if reason is not None:
            zero_dealt += 1
            reasons[str(reason)] = reasons.get(str(reason), 0) + 1
            continue
        dealt += 1
        requested = abs(Decimal(str(row.get("requested_quantity") or "0")))
        filled = abs(Decimal(str(row.get("dealt_quantity") or "0")))
        if filled < requested:
            partial += 1
    return {
        # Every order the venue answered, so the three counts below are readable as shares of it.
        "orders": len(rows),
        "dealt": dealt,
        "partial": partial,
        "zero_dealt": zero_dealt,
        # Named reasons rather than a total, because they are not one fact: `absent`,
        # `nontradable` and `no_trade` are facts about the MARKET, and `unfunded` is a fact about
        # the account. A reader asking what the market refused them must not be handed their own
        # empty purse in the same number.
        "reasons": dict(sorted(reasons.items())),
    }
