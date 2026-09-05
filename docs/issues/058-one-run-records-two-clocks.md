# 058 -- one run records fills in UTC and valuations in the venue's offset

**Status:** **CLOSED 2026-09-03** by record `146` (deletion campaign Step 5). The fill row's `event_time` is stamped in the strategy agenda's zone like every other table's, and the tables are parquet with a `timestamp[us, tz]` column, so the zone travels with the file.

**Status when filed:** open. Found 2026-09-03 by the scenario testbed run 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-008**), against `vqapr-0.3.0`. Confirmed
against source the same day.

**Touches:** `src/vqapr/exchange/execution_table.py:334` (`target_at=target_at.astimezone(UTC)`);
`src/vqapr/flow/simulation.py:977-985` (the fill row's `event_time` is that `target_at`);
`src/vqapr/evidence/recorder.py:34-86` (every other table's `event_time` is the agenda instant as
declared, in its own zone).

## What happens

In one strategy record:

```
vqapr.account  "event_time": "2016-12-16T15:40:00+09:00"
vqapr.fill     "event_time": "2016-12-16T06:35:00+00:00"
```

Both are correct instants. A reader lining a fill up against the valuation that followed it sees
two clocks for one run and converts by hand before comparing rows across tables. The agent
converted everything to Asia/Seoul itself.

## Why

The execution table normalises the fill target to UTC when it builds the `ExecutionTarget`; the
agenda instants that stamp valuation, decision and weight rows keep the zone the agenda declared.
Nothing chose this; the two paths were written at different times.

## What to do

One offset convention for every recorded instant -- the venue's zone, since the agenda declares
it and the user reads in it, or UTC everywhere -- applied where the envelope is stamped rather
than where each instant is computed. Step 5 of the deletion campaign (records to parquet,
`timestamp[us, tz]`) is the natural place, because the column type will then carry the zone and
the choice has to be made once.
