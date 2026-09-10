# `check` derives the run's agenda twice, and on a three-year run that is the whole of its cost

**Status: UNTRIAGED — found in the 0.12.0 scenario traces (`experiments/exp_235_the_scenario_trace/`), not yet judged by the owner.**

| | |
|---|---|
| vqapr version | `0.12.0` (develop `34f26371`) |
| reported | 2026-09-10 |
| reporter | the 0.12.0 scenario stepper, trace `03_check_changed` |
| evidence | `check sample-run` on the sample door: 86,499 calls, 3,624 ms |

## What the trace shows

`vqapr check sample-run` (the sample's own run, 2022-01-04 ~ 2024-12-30, 735 sessions) spends
3,455 of its 3,624 ms deriving the agenda -- twice:

| where | call | ms |
|---|---|---:|
| `judgments` → `_judge_execution_ordering` → `derived_agenda` | `#362` | 1,782 |
| `preflight_run` → `derived_agenda` | `#44533` | 1,673 |

Each derivation is ~42,000 profiled calls (`_local_date` per session and more). The two answers
are the same agenda for the same definition. The execution-table judgment that used to cost
11.5 s here (0.11.0 stepper, three content scans) is now a digest compare at `#42201`, 3.9 ms
(record `234`), which is what makes the agenda the visible remainder.

`run` pays the same twice when it preflights (`require_judged` then the freeze).

## Why it matters

A judgment and the freeze that follows it should share the facts they derive from the same
definition, the way `Workspace.require_verified` memoizes a digest per workspace object. For a
minute-grained agenda the derivation is proportionally larger.

## What a fix might look like

Derive the agenda once per `check`/`run` and hand it to both the judgments and the freeze (the
judgments already take `agenda` as a callable; the freeze could take the derived value instead of
re-deriving). Not measured beyond the trace above.
