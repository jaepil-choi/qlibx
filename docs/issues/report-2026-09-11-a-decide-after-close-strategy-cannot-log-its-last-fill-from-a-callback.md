# A decide-after-close strategy cannot log its last fill from a callback, because no callback follows it

**Kind: constructive feedback.** This is not a defect. The record holds the fill. The pattern for
logging fill-dependent facts is the missing piece.

**Status: RECEIVED 2026-09-11 (접수).** Confirmed from the B-2 transcript. The strategy scaffold and
`make-strategy` will say it where an author writes the log: record the decision in the callback,
read fill prices and quantities from `vqapr.fill` (which `vqapr export` writes as `fills.csv`), and
no callback follows the last fill. Campaign `redesign/one-reading`.

| | |
|---|---|
| vqapr version | `0.14.4` |
| installed from | `vqapr-0.14.4-py3-none-any.whl` built in `vqapr/dist/` from develop `b8b47e6c`, copied into each run directory |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-incr-testbed`, run `B-2` (sonnet 5), agent session |
| python / OS | 3.12.13 / Windows 11 |

## What I was doing

The task asked for a log of entries and exits with the fill-day price. B-2 decides after the close
of day t, at 15:31, and fills at the close of t+1. It writes its log with `self.recorder.append`
inside `decide`.

## What happened

An entry's price is the fill price, which B-2 only learns at the next callback. The run's last
fill, on 2024-12-30, has no callback after it. B-2 wrote the consequence into its summary: the last
decision opens and closes nothing, and only resolves and logs the day before. So its log is missing
the six entries and exits that the answer key and B-1 have on 2024-12-30.

B-1 avoided this in two ways. It decides at 15:29 on the fill day, so a callback exists on every
fill day. Its callback also logs only the decision, with the fill date. The fill-day price is
attached after the run, by an export script that looks the date up.

## Impact

Six rows missing from the deliverable, which the agent attributed to the framework. Any strategy
that logs fill outcomes from its own callbacks will lose the last fill the same way.

## What would have prevented it

- **Say it in `make-strategy`.** Log the decision in the callback. Read fill prices and quantities
  from `vqapr.fill` afterwards, where every fill including the last one is recorded.
- **Or put it in the event-log recipe.** The feature request for copyable strategy recipes asks for
  one.
