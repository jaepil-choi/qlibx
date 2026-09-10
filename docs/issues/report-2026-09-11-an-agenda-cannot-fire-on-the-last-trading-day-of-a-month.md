# An agenda cannot fire on the last trading day of a month, so three agents rebalanced a month-end strategy three different ways

**Status: UNTRIAGED — reported by testbed, not yet judged by the owner.**

| | |
|---|---|
| vqapr version | `0.14.2` |
| installed from | `vqapr-0.14.2-py3-none-any.whl` built in `vqapr/dist/`, copied into each run directory |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-ab-testbed`, runs `B-1` (opus), `B-3` (sonnet), `B-4` (fable), agent sessions |
| python / OS | 3.12.13 / Windows 11 |

## What I was doing

An A/B experiment. Each agent got the same data and one prompt: KOSPI200 members, 12-month
momentum, and "매월 마지막 거래일에 모멘텀 상위 30종목을 동일비중으로 보유" (hold the top 30 by
momentum, equal weight, rebalanced on the last trading day of each month), 2018–2024. Condition B
had vqapr 0.14.2 and its skills installed, and each B agent ran a fresh session with no history.

## What I expected

A way to declare "the last trading day of each month" as the strategy's clock. The shipped skills
state what exists, and it is not that:

- `run-backtest/SKILL.md` lines 27–28: "`every: 1d` with `at` is one decision a day; `every: 1M`
  the first trading day of each month".
- `run-backtest/references/run-declaration.md` line 29: "`1w` fires on the first trading day of each
  ISO week, `1M` on the first trading day of each calendar month".

Nothing names a month-end form or the recommended pattern for one. This is a missing capability,
not a disagreement between two documents.

## What happened

Nothing refused. Each agent worked around the gap on its own, and each chose differently:

| agent | what it declared | when the month-end portfolio actually filled |
|---|---|---|
| B-1 (opus) | `every: 1d`, with the 84 month-end session dates hard-coded in the strategy file (the agent said the KRX holiday calendar is published in advance, so it is not look-ahead) | 15:30 close of the month's last session, deciding at 15:29 on the prior close |
| B-3 (sonnet) | `every: 1M`, rebalancing moved to the next month's first session. The agent wrote that "vqapr's `agenda` can only fire on the *first* trading day of a period, not the last" | 09:00 **open** of the next month's first session |
| B-4 (fable) | `every: 1M`, next month's first session | 15:30 **close** of the next month's first session |

Rebased to 100 on 2018-01-31, the three final indices were 81.8 (B-1), 61.6 (B-3) and 84.4 (B-4).
The three condition-A agents that used pandas without vqapr, on the same prompt, ended within
69.3–79.0. **On this mission the framework runs spread more than the runs without the framework,
and this one decision accounts for most of the gap.** The B-1 workaround is also the only one that
matches the prompt, and it puts a calendar into strategy code.

Full tables: `kwam-enhanced-index/vqapr-ab-testbed/analysis/RESULT.md`, §2–§3.

## Reproduction

Try to declare a run whose strategy acts on the last trading day of each month. No value of
`every` expresses it. There is no refusal to reproduce: the three workarounds above are the
evidence. Seen in 3 of 3 B agents.

## Impact

Worked around three ways, and the workarounds change the result: with the same prompt, the fill
moves from month-end close, to next-day open, to next-day close. A user comparing their
framework result with a paper that rebalances at month-end will be off by one session, or will
hard-code a calendar.

## What would have prevented it

An agenda form for the last trading day of a period, or a documented recommended pattern for
month-end rebalancing in `run-backtest` (for example, `every: 1d` plus a check against the
registered calendar inside `decide`), so that three readers of the same skill choose the same thing.
