# A decide-after-close run is refused on every Friday by `within: 1d`, and the second refusal for the same occurrences says to widen a run end that is not the problem

**Status: RECEIVED 2026-09-11 (접수) — confirmed against `develop` `ee2e2711`.** Two doors refuse the same occurrences: `flow/declaration/judgments.py::_judge_execution_ordering` (`execution.not_after_decision`) and `flow/declaration/preflight.py::_validate_execution_targets` (`execution.target_outside_horizon`) each list every occurrence `select_target` cannot bind, and the second's `fix` names the run end whether the missing instant lies inside the horizon or past it. Neither says what `within` measures or names the end record `237` describes.

| | |
|---|---|
| vqapr version | `0.14.4` |
| installed from | `vqapr-0.14.4-py3-none-any.whl` built in `vqapr/dist/` from develop `b8b47e6c`, copied into each run directory |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-incr-testbed`, run `B-2` (sonnet 5), agent session |
| python / OS | 3.12.13 / Windows 11 |

## What I was doing

An A/B experiment on adding one strategy to an existing workspace. The workspace already held a
completed momentum run that decides at 15:29 and fills at 15:30 on the same day, with
`fill: {at: "15:30", within: "1d"}`. The new strategy decides after the close of day t and fills at
the close of t+1. The agent declared `agenda: {every: 1d, at: "15:31"}` and kept the momentum run's
fill block.

## What I expected

Either the run to be accepted, or a refusal that says why a one-day window fails and what works.

## What happened

`vqapr check` refused with two failures. Both list the same 403 occurrences:

```text
execution.not_after_decision (412)
  observed: strategy 'gap-reversal-enhanced' fills at the first execution instant after the
            decision, at 15:30:00 Asia/Seoul, within 1d; 403 occurrence(s) with no such instant
  examples: agenda-2017-12-28T1531, agenda-2018-01-05T1531, agenda-2018-01-12T1531, ...
  fix:      move the decision earlier than the instant it should fill at, extend the run end, or
            loosen the fill's `at`/`after`/`within`

execution.target_outside_horizon (412)
  examples: the same 403
  fix:      widen the run end past 2024-12-31T23:59:59+09:00 to cover the required execution
            instant, move the decision earlier, or loosen the fill's `at`/`after`/`within` so an
            instant after every decision qualifies
```

- **The refused occurrences are Fridays and days before a market holiday.** 2018-01-05, -12, -19
  and -26 are Fridays, and 2017-12-28 precedes the 2017-12-29 year-end closure. A 15:31 decision on
  a Friday has no 15:30 instant within 24 hours, because `within` counts wall-clock time, not
  sessions.
- **Nothing the agent could read says `within` is wall-clock time.** The only description is the
  `vqapr new run` template comment: "`within`: maximum gap, else the run is refused before it
  starts". The `run-backtest` skill does not mention the fill window.
- **The second failure's fix is wrong for 402 of the 403 occurrences.** They lie in the middle of
  the run, so no run end can fix them. The second failure repeats the first one's occurrences under
  a different code and points at the end.

The agent widened the window to `within: "10d"`. `check` then refused one occurrence, the data's
last session at 2024-12-30T15:31, again under both codes. The second fix again said to widen the
end past 2024-12-31, but the execution table ends on 2024-12-30.

The agent found the working answer itself, an end between the last fill and the last decision:
`end: "2024-12-30T15:30:01+09:00"`. Record `237` (issue `099`) calls this the only correct end for a
decide-after-close, fill-next-close strategy. Neither refusal names it.

## Reproduction

In a workspace with a daily KRX execution table, declare a run with
`agenda: {every: 1d, at: "15:31"}`, `fill: {at: "15:30", within: "1d"}` and an `end` after the
table's last session. Run `vqapr check <run>`.

## Impact

It cost two `check` cycles and a guessed window of ten days, on the most common daily research
clock. The end the agent chose is correct only because it recognised the pattern. B-1, the opus run
on the same task, avoided both refusals by deciding at 15:29 on the fill day, as the momentum run
does.

## What would have prevented it

- **Report each occurrence once.** An occurrence whose missing instant lies inside the horizon is a
  window problem. `target_outside_horizon` should not also claim it or suggest a later end.
- **Say what the window measures.** When the refused occurrences fall before weekends or holidays,
  say that `within` is wall-clock time. Name the longest gap between sessions in the run as the
  smallest window that works.
- **Name the end that works.** When the only unresolved occurrence is the table's last session,
  suggest an end between that session's fill and its decision, as record `237` describes.
