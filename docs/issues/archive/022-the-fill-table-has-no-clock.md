# 022 — `vqapr.fill` carries none of the five envelope fields the skill guarantees

**Status:** **closed** by `docs/implementations/093-the-fill-table-has-a-clock.md`
(branch `fix/022-fill-envelope`). Fill rows now carry all five envelope fields. The cause was
structural: these rows stage straight into the run-state chunks and never pass through the
`InvocationRecorder` that stamps every other table. This also resolves `docs/issues/archive/024`'s
unexplained `formations: 1`, with no change to `public.py` - the counter was right, its data was
missing.

**Status when filed:** open. Found 2026-08-30 by the final first-time-user journey in
`kwam-enhanced-index/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-011**,
`slowed`.
**Touches:** `src/vqapr/flow/run_state.py:180-217` (`_fill_rows`).

## The guarantee

> Every row of every table also carries the same five envelope fields: `run_id`, `producer_id`,
> `stage`, `event_time` and `sequence` — which run wrote it, what wrote it, at what point, when the
> fact happened, and in what order. A table cannot declare one of these as a column of its own.

## What is there

```
vqapr.account row keys: account_version, cash, event_time, instrument, nav, observed_at,
                        price, producer_id, quantity, run_id, sequence, stage
vqapr.fill    row keys: account_version, cash_delta, commission, dealt_quantity, instrument,
                        kind, price, reason, requested_quantity, tax
missing from vqapr.fill: event_time, producer_id, run_id, sequence, stage
```

`vqapr.account` has all five. The reporter's own diagnostic table has all five. `vqapr.fill` has
none.

Confirmed in this repository: `_fill_rows` (`src/vqapr/flow/run_state.py:199-215`) constructs each
row from exactly those ten keys and no envelope is added.

## Why this is the table it hurts most on

The skill says so itself:

> **This is the table cost questions are asked of** — commission and tax are per fill and per side,
> so a category's true cost is a sum over this table

A cost question with a date in it — *"what did the 2022 rebalances cost?"* — cannot be answered from
this table at all, because no row says when it happened. `account_version` is the only ordering
available, and it numbers rebalances rather than dating them.

## It also silently breaks a reported counter

`vqapr show run` reports a per-table `formations` count. In this repository that count is
`len({str(row.get("event_time")) for row in rows})` (`src/vqapr/public.py:651`). Because every
`vqapr.fill` row lacks `event_time`, `row.get` returns `None` for all of them and the set collapses
to one element — which is exactly the `"formations": 1` the journey reported for 13,012 fills across
7 distinct instants, and could not construct any reading for. See **024**; that half of 024 is a
symptom of this file, not a separate defect.

## The verification the reporter wanted and could not do

Confirming that the T+1 change had actually moved the fill a session later. The direct way is to
read a fill's timestamp. Instead they verified by price: the first fill of `ff3-t1-final` is A000020
at 9750.0, the venue table has A000020 at 9710.0 on 2019-07-01 and 9750.0 on 2019-07-02, and the
same-session run filled the same name at 9710.0. Indirect — 2019-07-03 also closed at 9750.0 — and
the best the table allows. That evidence is what the headline result of the whole journey rests on.

## What closes it

`code` if the envelope is meant to be there — add it in `_fill_rows`, where `entry.version` is
already in hand and the occurrence instant is in scope.

`docs` if fills are deliberately exempt, in which case **both** skill sentences need an exception
written into them: *"every row of every table"* and *"a table cannot declare one of these as a
column of its own"*. Note that the second sentence is what would otherwise let a venue author add
their own `event_time` column as a workaround.

The docstring on `_FILL_TABLE` argues the table is package-owned and fixed-schema precisely so a
reader can trust it. That argument is stronger, not weaker, with the envelope on it.
