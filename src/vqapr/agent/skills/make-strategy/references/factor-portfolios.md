# A factor is a portfolio

## In plain words

A factor's return — SMB, HML, momentum, any long-short spread — is the return of the portfolios
that mimic it. In vqapr each of those portfolios is a strategy: it decides which names to hold and
how much, the account holds them between decisions, and its daily NAV return is what that leg
earned. The factor is arithmetic on those returns, after the runs.

A DataModel cannot give you this. It returns a value per instrument — an exposure, a loading, a
size — and a return needs something held.

Built this way on Korean data (KOSPI and KOSDAQ, July 2018 to December 2024, about 1,500 to 1,800
names a year), daily SMB and HML tracked a published replication at 0.989 and 0.974 correlation, and
RMRF exactly. Recomputing the same membership in pandas moved the daily MSE by only 15 and 24 bp²:
that small difference is drift by shares, halts and delistings — what the account decided, where a
script decides it silently.

## The recipe: Fama-French 2×3

1. **Register what you have, with honest "when was this known" stamps.** A daily price and market
   cap are known at that day's close. A month-end listing is known at that month-end's close. An
   annual statement is known three months after its fiscal year ends — the usual availability rule,
   written once as a registration fact instead of a merge nobody checks. The price table is also
   the venue's table, and a halted day does not fill.
2. **One strategy per leg: S1 S2 S3 B1 B2 B3.** Each decides once a year, on July's first trading
   day, from what it can see then: June's last market cap, the June listing, and the newest
   statement of the previous fiscal year. It sorts with the package's Fama-French helpers —
   breakpoints from the reference market only, applied to every eligible name — and asks to hold
   its names in proportion to size. Between Julys it simply holds its shares, so the weights drift
   the way a value-weighted buy-and-hold does.
3. **One more leg for the market.** Register the index level as a one-instrument price table (the
   roster kind is `index`); a strategy holding it fully invested earns exactly the index return.
4. **Each leg is its own run** — a run is one model — on the frictionless `academic` venue,
   filling at the decision day's close. Either make every listing divisible, so each leg holds
   exactly the value weights it asked for, or keep whole shares with an account large enough that
   rounding is noise (10 trillion KRW left 4e-8 of NAV in cash).
5. **Read each run's daily returns back and do the arithmetic.** SMB = mean(S) − mean(B),
   HML = mean(S3, B3) − mean(S1, B1), RMRF = market leg − RF.

## Why six long-only legs, not one signed book

A signed SMB book built with `Rebalance.signed` holds all six portfolios in **one** account.
Between rebalances they drift against each other, so its daily return stops being "the average of
three small portfolios minus the average of three big ones" — a definition that re-averages every
day. Six accounts reproduce it exactly: value weights with drift inside each leg, and the
equal-weight average across legs taken by arithmetic afterwards.

## The names

One file per leg — there is no config channel, so the leg is a constant in the file and six legs
are six ids:

```python
from decimal import Decimal
from vqapr import authoring as va
from vqapr.public import fama_french_assign, fama_french_cut_points

SIZE, BM = "S", "1"                     # this file is S1; S2 ... B3 differ only here
SEOUL = "Asia/Seoul"

class FfLeg(va.StrategyModel):
    def inputs(self):
        return {
            "px": va.DatasetInput(dataset_id="prices", fields=("market_cap", "is_trading_halt"),
                                  lookback=va.CalendarLookback(days=14, timezone=SEOUL)),
            "ls": va.DatasetInput(dataset_id="listing", fields=("market",),
                                  lookback=va.CalendarLookback(days=45, timezone=SEOUL)),
            "fs": va.DatasetInput(dataset_id="financials",
                                  fields=("fiscal_yyyymm", "total_equity"),
                                  lookback=va.CalendarLookback(days=600, timezone=SEOUL)),
        }

    def decide(self, call):
        if call.evaluation_time.month != 7:
            return va.Hold(reason="forms only in July")
        caps = call.read("px", "market_cap").current()   # the newest cross-section
        # caps.at is its instant: assert it is June's last close before trusting it
        ...  # eligibility, book equity from call.read("fs", ...).matrix(), bm = be / me
        size = fama_french_assign(
            me, thresholds=fama_french_cut_points(me, reference=kospi, fractions=(Decimal("0.5"),)),
            labels=("S", "B"))
        cuts = fama_french_cut_points(bm, reference=kospi, fractions=(Decimal("0.3"), Decimal("0.7")))
        bucket = fama_french_assign(bm, thresholds=cuts, labels=("1", "2", "3"))
        chosen = {n: me[n] for n in me if size[n] == SIZE and bucket[n] == BM}
        if not chosen:
            return va.Hold(reason=f"no eligible name in {SIZE}{BM}")
        return va.Rebalance.of(long=chosen, invested=1)   # conviction in proportion to size
```

- `CalendarLookback`, not `RowsLookback`: a sort is cross-sectional, and every name must see the
  same window. `current()` is the newest cross-section; `.at` says which instant it is.
- The market leg returns `va.Rebalance.of(long={"KOSPI": 1}, invested=1)` against its own
  one-instrument execution table.
- The run: `agenda: {every: 12M, at: "15:29"}` with `start` on the first of July, the fill at the
  close (`15:30`, `trade_price: close`), the `academic` venue, and a large `initial_account`.
- Exact weights: in the venue's `TradeRule` (the `vqapr new exchange --profile academic`
  scaffold), `fractional_allowed=True` with a fractional `quantity_step` makes a listing divisible,
  and quantities are then not rounded at all. A pandas rebuild that treats halts and delistings
  the way the account does matched such legs to the last digit; one that drops delisted names and
  re-spreads their weight will not, and that difference is the account's decision, not rounding.
- Reading back: `strategy_report(store, "<run-id>").performance.returns` per leg. Its instants
  mix a fixed offset with zone-aware ones, so pass `utc=True` when handing them to pandas.
- A date-only series such as a risk-free rate registers as `grain: instant`. There is no public
  Python reader for a registered dataset's rows; `vqapr show dataset <id> --limit N` returns them
  as JSON.

## What it cannot express exactly

- **The June-end formation.** There is no month-end cadence: `every: 12M` fires on the first
  trading day of the run's first month, and a book fills strictly after the decision. So the new
  book is decided on July's first session from June-end data and fills at that session's close;
  the first July session still carries last year's book. Measured: 6 and 5 bp² of daily MSE on
  SMB and HML.
- **Delisted holdings.** A held name that stops trading is never sold; it stays at its last price
  until the run ends. Money in a name that cannot be sold — halted or delisted — cannot pay for the
  next book, and the smallest new buys go unfilled (recorded `no_trade`). In the replication that
  was up to 2.2% and 5.8% of a leg's NAV respectively. Read `vqapr.fill` to see it per rebalance.
- **A second definition is a second set.** A different book-equity rule is six more files, six more
  runs, and a separate registration if it reads new fields.
