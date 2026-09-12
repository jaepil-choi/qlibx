"""One leg of the Fama-French 2x3 sort, value-weighted, formed once a year.

prepare.py writes six copies of this file (ff_s1.py ... ff_b3.py), changing only SIZE and BM,
because a StrategyModel has no config channel: one arm of a methodology is one file and one id.

What a leg does at its one decision a year (the run's `agenda: every: 12M` fires on the first
trading day of July, 15:29 Asia/Seoul):

- ME is the market cap at the newest close it can see, which is June's last close.
- The universe is the June month-end listing: KOSPI or KOSDAQ, not a SPAC, not a financial,
  not halted at June's last close.
- BE comes from the newest annual statement whose fiscal year ENDED in the previous calendar
  year; the financials dataset is registered with available_at = fiscal-year end + 3 months, so
  a statement that was not yet known cannot be read at all.
- BE = total_equity - noncontrolling_interest (missing NCI is 0); controlling_equity when
  total_equity is missing; BE <= 0 is dropped. Financials are in KRW thousand.
- Breakpoints: size median and BM 30/70 from KOSPI names only, applied to both markets, with
  vqapr.public.fama_french_cut_points / fama_french_assign (a value on a cut stays low).
- The leg holds its names with conviction = ME, so the package sizes them value-weighted; the
  account then holds shares until the next July, so weights drift buy-and-hold.
"""

from decimal import Decimal

import numpy as np

from vqapr import authoring as va
from vqapr.public import fama_french_assign, fama_french_cut_points

SIZE = "S"  # S (ME <= KOSPI median) or B
BM = "1"  # 1 (BM <= KOSPI 30%), 2, 3 (BM > KOSPI 70%)

SEOUL = "Asia/Seoul"


class FfLeg(va.StrategyModel):
    """Value-weighted Fama-French leg SIZE+BM, re-formed on the first trading day of July."""

    def inputs(self):
        return {
            # 14 calendar days back from the decision: the newest instant is June's last close.
            "px": va.DatasetInput(
                dataset_id="ff-prices",
                fields=("market_cap", "is_trading_halt"),
                lookback=va.CalendarLookback(days=14, timezone=SEOUL),
            ),
            # the June month-end listing row
            "ls": va.DatasetInput(
                dataset_id="ff-listing",
                fields=("market", "is_spac", "is_financial"),
                lookback=va.CalendarLookback(days=45, timezone=SEOUL),
            ),
            # far enough back to reach a fiscal year that ended early in the previous year
            "fs": va.DatasetInput(
                dataset_id="ff-financials",
                fields=(
                    "fiscal_yyyymm",
                    "total_equity",
                    "noncontrolling_interest",
                    "controlling_equity",
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
                continue  # halted at formation, or no halt flag: out for the year
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
        # conviction = ME: the package normalises it into value weights and fills whole shares
        return va.Rebalance.of(long=chosen, invested=1)


def _book_equity(call, *, fiscal_year: int) -> dict[str, float]:
    """BE in KRW from the newest statement whose fiscal year ended in `fiscal_year`."""
    fy_w = call.read("fs", "fiscal_yyyymm")
    fy = fy_w.matrix()
    te = call.read("fs", "total_equity").matrix()
    nci = call.read("fs", "noncontrolling_interest").matrix()
    ce = call.read("fs", "controlling_equity").matrix()
    with np.errstate(invalid="ignore"):
        want = np.floor(fy / 100.0) == fiscal_year
    has = want.any(axis=0)
    last = want.shape[0] - 1 - np.argmax(want[::-1], axis=0)
    out: dict[str, float] = {}
    for j, name in enumerate(fy_w.instruments):
        if not has[j]:
            continue
        i = last[j]
        t, n, c = te[i, j], nci[i, j], ce[i, j]
        if np.isfinite(t):
            value = t - (n if np.isfinite(n) else 0.0)
        elif np.isfinite(c):
            value = c
        else:
            continue
        out[name] = float(value) * 1000.0  # KRW thousand -> KRW
    return out
