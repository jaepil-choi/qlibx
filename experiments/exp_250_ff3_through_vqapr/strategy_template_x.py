"""One leg of the Fama-French 2x3 sort -- arm ff3x: BE falls back to assets - liabilities.

Identical to strategy_template.py (arm ff3) except for the book equity of a name whose
statement carries neither total_equity nor controlling_equity. The specification names no rule
for that case; in this data it is every FY2017 statement but about 220, so arm ff3 forms its
2018 books from 199 names. Total equity is assets minus liabilities by the balance-sheet
identity (exact on 99.95% of the rows that carry all three), so this arm uses
total_assets - total_liabilities - noncontrolling_interest (missing NCI is 0) there.

A different rule is a different arm, and a StrategyModel has no config channel, so this is a
second template, six more files and six more ids (ffx-s1 ... ffx-b3), not a flag.
"""

from decimal import Decimal

import numpy as np

from vqapr import authoring as va
from vqapr.public import fama_french_assign, fama_french_cut_points

SIZE = "S"  # S (ME <= KOSPI median) or B
BM = "1"  # 1 (BM <= KOSPI 30%), 2, 3 (BM > KOSPI 70%)

SEOUL = "Asia/Seoul"


class FfLegX(va.StrategyModel):
    """Value-weighted Fama-French leg SIZE+BM, re-formed on the first trading day of July."""

    def inputs(self):
        return {
            "px": va.DatasetInput(
                dataset_id="ff-prices",
                fields=("market_cap", "is_trading_halt"),
                lookback=va.CalendarLookback(days=14, timezone=SEOUL),
            ),
            "ls": va.DatasetInput(
                dataset_id="ff-listing",
                fields=("market", "is_spac", "is_financial"),
                lookback=va.CalendarLookback(days=45, timezone=SEOUL),
            ),
            # a registration of its own: the same statements with assets and liabilities exposed,
            # so arm ff3's `ff-financials` stays exactly what its records read
            "fs": va.DatasetInput(
                dataset_id="ff-financials-x",
                fields=(
                    "fiscal_yyyymm",
                    "total_equity",
                    "noncontrolling_interest",
                    "controlling_equity",
                    "total_assets",
                    "total_liabilities",
                ),
                lookback=va.CalendarLookback(days=600, timezone=SEOUL),
            ),
        }

    def decide(self, call):
        now = call.evaluation_time
        if now.month != 7:
            return va.Hold(reason=f"forms only in July, called {now.date()}")

        me_cs = call.read("px", "market_cap").current()
        halt = call.read("px", "is_trading_halt").current()
        formed = me_cs.at.astimezone(now.tzinfo) if me_cs.at is not None else None
        if formed is None or formed.month != 6 or formed.year != now.year:
            raise ValueError(f"expected June's last close as the newest price, got {formed}")

        market = call.read("ls", "market").current()
        spac = call.read("ls", "is_spac").current()
        fin = call.read("ls", "is_financial").current()
        listed_at = market.at.astimezone(now.tzinfo) if market.at is not None else None
        if listed_at is None or listed_at.month != 6 or listed_at.year != now.year:
            raise ValueError(f"expected the June month-end listing, got {listed_at}")

        be = _book_equity(call, fiscal_year=now.year - 1)

        me: dict[str, Decimal] = {}
        bm: dict[str, Decimal] = {}
        kospi: set[str] = set()
        for name, cap in me_cs.items():
            if cap is None or not cap > 0:
                continue
            if halt.get(name) is None or bool(halt[name]):
                continue
            mk = market.get(name)
            if mk not in ("KOSPI", "KOSDAQ"):
                continue
            if spac.get(name) is None or bool(spac[name]):
                continue
            if fin.get(name) is None or bool(fin[name]):
                continue
            b = be.get(name)
            if b is None or not b > 0:
                continue
            me[name] = Decimal(str(cap))
            bm[name] = Decimal(repr(b / float(cap)))
            if mk == "KOSPI":
                kospi.add(name)

        if not kospi:
            raise ValueError("no eligible KOSPI name to set the breakpoints")
        size_cut = fama_french_cut_points(me, reference=kospi, fractions=(Decimal("0.5"),))
        size = fama_french_assign(me, thresholds=size_cut, labels=("S", "B"))
        bm_cut = fama_french_cut_points(
            bm, reference=kospi, fractions=(Decimal("0.3"), Decimal("0.7"))
        )
        bucket = fama_french_assign(bm, thresholds=bm_cut, labels=("1", "2", "3"))

        chosen = {n: me[n] for n in me if size[n] == SIZE and bucket[n] == BM}
        if not chosen:
            return va.Hold(reason=f"no eligible name in {SIZE}{BM} this year")
        return va.Rebalance.of(long=chosen, invested=1)


def _book_equity(call, *, fiscal_year: int) -> dict[str, float]:
    """BE in KRW from the newest statement whose fiscal year ended in `fiscal_year`."""
    fy_w = call.read("fs", "fiscal_yyyymm")
    fy = fy_w.matrix()
    te = call.read("fs", "total_equity").matrix()
    nci = call.read("fs", "noncontrolling_interest").matrix()
    ce = call.read("fs", "controlling_equity").matrix()
    ta = call.read("fs", "total_assets").matrix()
    tl = call.read("fs", "total_liabilities").matrix()
    with np.errstate(invalid="ignore"):
        want = np.floor(fy / 100.0) == fiscal_year
    has = want.any(axis=0)
    last = want.shape[0] - 1 - np.argmax(want[::-1], axis=0)
    out: dict[str, float] = {}
    for j, name in enumerate(fy_w.instruments):
        if not has[j]:
            continue
        i = last[j]
        t, n, c, a, liab = te[i, j], nci[i, j], ce[i, j], ta[i, j], tl[i, j]
        n0 = n if np.isfinite(n) else 0.0
        if np.isfinite(t):
            value = t - n0
        elif np.isfinite(c):
            value = c
        elif np.isfinite(a) and np.isfinite(liab):
            value = a - liab - n0  # the arm's one difference: the balance-sheet identity
        else:
            continue
        out[name] = float(value) * 1000.0  # KRW thousand -> KRW
    return out
