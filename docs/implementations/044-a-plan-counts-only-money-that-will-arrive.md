# 044 — A plan counts only money that will arrive

Closes `docs/issues/archive/006-a-plan-funds-buys-with-proceeds-the-venue-refuses.md`, and fixes a Windows
concurrency defect found while verifying it.

## Why this exists

A fully-invested enhanced index ended its run on the first rebalance:

```
simulation.due.account_preparation: fill batch would make cash negative
```

`_apply_venue_rules` funds the batch's buys from the batch's sells, and the only thing that excused
an instrument from contributing was having no price. But the venue refuses a sell for a *different*
reason — the execution row says `is_tradable = false` — and the planner was never told, because
`simulation.py` passed prices alone:

```python
prices = {row.instrument: row.price for row in snapshot.rows if row.price is not None}
```

A halted name **has a price**, and must: canon 6.1 marks a position from a row whose `is_tradable`
is false, because a halt suspends trading and not valuation. So the planner reserved its sale
proceeds, sized buys against money that was never going to arrive, the venue published the sell as
typed `NONTRADABLE` zero-dealt evidence, the buys filled in full, and `Account.prepare_fill` caught
the overdraft at the last possible moment.

Reproduced in twelve lines — hold 100 halted shares, target a full rotation into one tradable name,
`cash_target=0` — the plan sells 100 and buys 99.74; the venue deals 0 and 99.74.

## Why it stayed hidden

Every book run so far kept cash. The long-short alpha lanes never target the whole account, and the
enhanced index parked its ETF sleeve in 20% cash, which quietly absorbed the missing proceeds.
Holding the sleeve as a *position* — the whole point of records 035–040 — removed the slack and
exposed this immediately.

It is not rare. On the KOSPI 200 panel the reproduction runs on, *every one* of 2,485 sessions
carries halted-but-priced rows: mean 84.5, max 241.

## What changed

`plan_orders` takes `tradable: Mapping[str, bool] | None`, forwarded to `_apply_venue_rules`, which
skips a name that is not fillable at this instant on both the funding and the spending pass.
`simulation.py` builds it from the snapshot it already has.

Two decisions worth stating:

- **The order is still emitted.** Only the funding arithmetic changed. `NONTRADABLE` is the
  evidence that the fund tried to sell and the market would not let it; suppressing the request
  would erase that, and the account would silently look like it never wanted to trade.
- **Absent means fillable.** A caller that passes nothing behaves exactly as before, so the
  parameter adds a capability without moving any existing result.

This is adjacent to issue 002 but not in it. 002 lists venue *sequencing* — sells settling before
buys, costs consuming allocated cash. This is a planner defect: it counted proceeds from a sale
that cannot happen at all, which no ordering inside the venue could fix.

## The Windows race found while verifying it

`tests/test_workspace_concurrency.py::test_parallel_registrations_all_survive` failed about 1 run
in 10 — on clean `0.1.0a10` as well, so it predates this work, but it would have broken the
two-overlay parallel run this fix exists to enable.

The first attempt was wrong and is worth recording as such. The error surfaced as
`workspace.open.unreadable`, so the retry went on the **read**; failures continued at 3/30. Capturing
the worker's actual stderr instead of reading the symptom named the real one:

```
PermissionError: [WinError 5] Access is denied:
  '...\.workspace.yaml.ck7xug5s.tmp' -> '...\workspace.yaml'
```

The failure is the **write**. POSIX `rename` is unconditional, so a reader holding the old inode
keeps it and the swap succeeds; Windows refuses `os.replace` onto a path another process has open.
The workspace lock does not cover it, deliberately: it serialises writers against each other, which
is what prevents a lost update, while a reader takes no lock because a run reads the workspace on
every callback. So a writer can hold the lock, be the only writer, and still be refused by a reader
that arrived between its own read and its write.

Both operations now retry for up to ten attempts with linear backoff. A swap completes in
microseconds, so outlasting it is proportionate — and a genuine permission problem still fails,
because it outlasts the retries.

## Verification

```text
uv run pytest -q                         649 passed (twice, random order)
concurrency test, 30 isolated runs       0 failures   (baseline 1/12; read-only retry 3/30)
```

`tests/orders/test_planning.py::test_a_halted_sale_does_not_fund_a_buy` pins the behaviour: the
halted sell is still requested, nothing is bought against it, the same batch with the halt lifted
*is* funded by the sale, and a caller passing no tradability map is unchanged.
