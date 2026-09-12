# 006 — A plan funds buys with proceeds the venue refuses

**Status:** closed 2026-08-21 by
`docs/implementations/044-a-plan-counts-only-money-that-will-arrive.md`.
Found 2026-08-21 running a fully-invested enhanced index, where it ended the run on the first
rebalance.
**Touches:** `src/vqapr/orders/planning.py`, `src/vqapr/flow/simulation.py`,
`src/vqapr/workspace.py`

> **Resolved as proposed.** `plan_orders(..., tradable=...)` carries the snapshot's own
> `is_tradable`, and `_apply_venue_rules` skips a name that is not fillable on both the funding
> and the spending pass. The order is still emitted, so the `NONTRADABLE` evidence survives; an
> instrument absent from the map is assumed fillable, so every existing caller is unmoved.
>
> Verifying it exposed a second, unrelated defect that would have broken the parallel run this
> fix enables: `os.replace` on Windows is refused while a reader has the workspace open, about 1
> run in 10 with eight processes. Both the read and the swap now retry. The first attempt put the
> retry on the read alone, because that is where the error *surfaced* — reading the symptom rather
> than the stderr, which named the write.

## What happens

`_apply_venue_rules` funds the batch's buys from the batch's sells:

```python
available = account.cash
for instrument_id in ordered:
    delta = _delta(instrument_id)
    if delta >= 0 or instrument_id not in prices:
        continue
    notional = rules.notional(instrument_id, delta, prices[instrument_id])
    available += notional - rules.charge(Side.SELL, notional, instrument_id).total
```

The only thing that excuses an instrument from contributing is having no price. But the venue
refuses a sell for a *different* reason — the execution row says `is_tradable = false` — and the
planner is never told:

```python
# simulation.py:801
prices = {row.instrument: row.price for row in snapshot.rows if row.price is not None}
```

A halted name **has a price**. It has to: canon 6.1 marks a position from a row whose
`is_tradable` is false, because a halt suspends trading, not valuation. So the planner reserves
its sale proceeds, sizes the buys against money that is never going to arrive, the venue publishes
the sell as a typed `NONTRADABLE` zero-dealt fill, the buys fill in full, and the account is
overdrawn.

`Account.prepare_fill` catches it at the last possible moment and ends the run:

```
simulation.due.account_preparation: fill batch would make cash negative
```

Reproduced in twelve lines: hold 100 halted shares, target a full rotation into one tradable name,
`cash_target=0`. The plan sells 100 and buys 99.74; the venue deals 0 and 99.74.

## Why it has been invisible

Every book run so far kept cash. The long-short alpha lanes never target the whole account, and
the enhanced index parked its ETF sleeve in 20% cash — that slack quietly absorbed the missing
proceeds. A **fully-invested** book has no slack, so the first halted holding it wants to sell
ends the run.

It is not rare, either. On the KOSPI 200 panel this reproduces on, *every one* of 2,485 sessions
carries halted-but-priced rows — mean 84.5, max 241.

This is adjacent to issue 002 but not in it. 002 lists "sells should settle before buys" and
"costs consume cash that the plan already allocated" as unmodelled venue sequencing. This is
narrower and is a planner defect rather than a venue one: the planner counts proceeds from a sale
that **cannot happen at all**, which no amount of ordering inside the venue can fix.

## Shape of the fix

The planner already asks the venue whether an instrument is tradable — `rules.tradable()` — but
that is the venue's *standing* declaration, not today's. Today's lives in the execution table and
stops at `simulation.py:801`.

Pass it down. `plan_orders(..., tradable=...)` carrying the snapshot's own `is_tradable` per
instrument, and `_apply_venue_rules` skips a name that is not tradable at this instant when it
adds up `available`.

Two details worth deciding deliberately:

- **Still emit the order.** The refusal is evidence: `NONTRADABLE` says the fund tried to sell and
  the market would not let it, and suppressing the request would erase that. Only the *funding*
  arithmetic should change.
- **Buys, too.** Reserving cash for a buy that gets refused is harmless to solvency — the money
  simply goes unspent — but it also clips other buys that would have fitted. Skipping non-tradable
  names on both sides puts the book closer to its target for the same reason.

## What not to do

Do not require the caller to hold a cash buffer. A buffer sized for the worst halt is dead weight
every other session, and it turns a planner defect into a research parameter — the same objection
that closed the equivalent question in issue 005.
