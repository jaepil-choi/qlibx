# Following the skills, three agents concluded a factor return series cannot be built through vqapr and computed it in pandas

**Status: UNTRIAGED — reported by testbed, not yet judged by the owner.**

| | |
|---|---|
| vqapr version | `0.14.2` |
| installed from | `vqapr-0.14.2-py3-none-any.whl` built in `vqapr/dist/`, copied into each run directory |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-ff3-testbed`, first pass (runs `B-1` opus, `B-2` sonnet, `B-3` fable) and second pass (run `B-1` opus), agent sessions |
| python / OS | 3.12.13 / Windows 11 |

## What I was doing

The task was to implement the Fama-French three factors (RMRF, SMB, HML) as daily returns to a
written specification: June 2×3 sorts with KOSPI breakpoints, value-weighted portfolios, KOSPI
minus CD91 for the market. The answer key is the published Kimchi factor series. In the first
pass, three agents had vqapr and its skills installed and were told only that vqapr was there.

## What I expected

The owner's intended path: register the tables; compute the June sorts in a DataModel; hold each of
the six portfolios as a StrategyModel on an `academic` venue; read each portfolio's NAV from its run
record; take SMB and HML as arithmetic on those NAV returns.

## What happened

No refusal. All three agents read the skills and decided vqapr could not express the task. Two
wrote down why; the third (sonnet) read `introduce-vqapr/SKILL.md` and went to pandas without
giving a reason.

- **opus**, decision 21 in its summary, translated from Korean: the make-datamodel table says "a
  factor exposure is a value, so DataModel", but the same document says a DataModel is for a
  reusable intermediate table and not to be inserted because the pipeline looks tidier. The
  deliverable is a daily factor series, no StrategyModel subscribes to it, and nothing is filled.
  So it used a standalone pandas script.
- **fable**, summary §3.3, translated: a DataModel yields one row per instrument per session, and a
  StrategyModel must pass through execution and the account. The StrategyModel path would produce
  numbers different from the definition through fill timing, fill price and account balance, and
  the DataModel path can only produce per-instrument values. Neither holds "value-weighted average
  of `ret`" as defined, so pandas.

The skill lines they were reading (shipped 0.14.2 copies):

- `make-datamodel/references/datamodel-or-strategy.md` line 39: "| a beta, a market cap, a factor
  exposure | DataModel | a value; nothing to fill |".
- Same file, lines 50–53: a DataModel is what a StrategyModel "reaches for when it needs a
  **reusable** intermediate table … Do not insert one because the pipeline looks tidier with it."
- `make-datamodel/SKILL.md` line 3: "reusable derived panels such as factor exposures, betas…".

No worked case says that a factor's **return** is the return of a portfolio, and so a StrategyModel.
Nothing says an academic venue with fractional listings reproduces a textbook value-weighted return
exactly. fable's worry was exactly that it would not.

**The path works.** In the second pass, the prompt required the framework path. opus built it with
two DataModel runs and six StrategyModel runs on an `AcademicExchange` venue, reading
`vqapr.account` through `read_strategy_table`. Its six portfolio returns matched its own independent
pandas rebuild with a maximum difference of 0.0. Its factors were the closest of all runs to the
published Kimchi series: MSE 457 bp² over RMRF+SMB+HML, against 469 bp² for the best pandas-only
run.

Full results: `kwam-enhanced-index/vqapr-ff3-testbed/analysis/RESULT.md`.

## Reproduction

Give a fresh agent the shipped skills and a factor-construction task that does not name the path.
In the first pass this happened 3 of 3 times (opus, sonnet, fable).

## Impact

Without an explicit mandate, the framework is skipped for one of the most common research tasks.
The factor legs are then built with no record, no point-in-time check and no fill model. A human
reading the same two skill passages would reach the same conclusion.

## What would have prevented it

A worked case row for "a factor's return", and one sentence in make-exchange or make-strategy
saying that an academic venue with fractional listings reproduces a value-weighted portfolio return
exactly, so arithmetic on the legs' NAV returns is the factor.

*Noticed while filing, not part of the observation:* the upstream working tree on 2026-09-11 has an
uncommitted change adding such a row to `datamodel-or-strategy.md`, and an experiment
`exp_250_ff3_through_vqapr/`. This report is the testbed evidence for that change.
