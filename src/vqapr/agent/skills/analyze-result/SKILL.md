---
name: analyze-result
description: Reads a finished vqapr run's records and turns them into answers, tables, and publication-quality figures — returns, costs, turnover, exposures, intended-versus-realized diagnostics, and attribution. Installs plotting libraries into the user's environment, with confirmation, when they are missing. Use when the user asks how a backtest performed, wants a chart, plot, table, tearsheet, or paper figure, wants to compare runs or strategies, or asks where a number in a result came from.
---

# Read a finished vqapr run

## Invoke the CLI through the active environment

Installing a console script into a virtual environment does not put it on the global shell PATH.
Use one launcher consistently:

- activated environment: `vqapr --help`
- uv-managed project: `uv run vqapr --help`

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed; the environment
is simply not activated. Apply the same prefix to every command below.

## Start from the report, not from the tables

`strategy_report` and `run_report` read a finished record back and compute, once, what a paper's
tables need. Reaching into the raw tables first means recomputing — differently — something the
package already computed.

```python
from decimal import Decimal
from pathlib import Path
from vqapr.public import run_report, strategy_report

store = Path(".vqapr")                       # the `store_root` `vqapr run` printed
one = strategy_report(store, "reversal")     # the run's only strategy, or "<id>" / "<id>@<fp8>"
every = run_report(store, "ff-arm", benchmark="bm-book", risk_free_annual=Decimal("0.03"))
one.as_record()                              # JSON-ready: Decimal as text, instants with offset
```

**These are library calls. There is no reporting CLI** — the values are the package's and the
picture is this skill's.

A `StrategyReport` has six sections; each is `None` with a reason in `omitted` when the record
cannot give it. What each holds, and the traps in reading them, is in
[references/report-sections.md](references/report-sections.md).

| section | answers |
|---|---|
| `performance` | NAV, returns, drawdown; annualised return, volatility, Sharpe, Sortino, Calmar; `by_year`, `by_month` |
| `book` | held / long / short counts, gross · net · long · short exposure, cash share, max weight, HHI |
| `attribution` | P&L per period by name and by side, plus `residual` |
| `trading` | realised and intended turnover, costs from fills, holding periods |
| `intent` | each decision's weights against the book that followed |
| `compliance` | per compliance rule: held / within tolerance / breached / unmeasured |

A `RunReport` adds `headline` (one row per strategy), `correlation` of period returns over the
instants every strategy shares, and `relative` against a `benchmark` **strategy of the same run** —
an index level is not in the record and is not invented.

## Two numbers that are asked for by the same word

**Three hit rates, three names.** `positive_period_share`, `position_hit_rate` and
`weight_sign_hit_rate` measure different things. Never report any of them as "hit ratio" without
saying which.

**Sharpe is against `risk_free_annual`, which is zero unless given** — the record holds no rate.
State the rate you used, every time you report a Sharpe.

**`periods_per_year` is inferred from the valuation grid** and the report says so (`inferred`).
Pass it to override, and state it beside any annualised number.

## Rendering a figure

vqapr computes the values and stops. **It ships no plotting library and no renderer**, on purpose
(PRD §9.4): the same values must be readable by any renderer, so the picture belongs to the
project.

That means the libraries a figure needs are usually **not installed**. Before writing plotting
code:

```bash
uv run python <skill>/scripts/check_plotting_env.py --project-root <project>
```

`<skill>` is the directory this `SKILL.md` is in. The script reports what is missing and prints the
command this project would use to add it — and **installs nothing**.

Then:

1. If the project already renders charts with something else, use that. Do not add a second one.
2. If something is missing, tell the user what and why, show the command, and **ask**. Adding a
   dependency changes their lockfile and their reproducibility.
3. Install only after they agree. Never add anything to vqapr itself.

Why this is a conversation rather than a step, and what to do when the user declines, is in
[references/plotting-environment.md](references/plotting-environment.md). Recipes for the usual
paper tables and figures, and the house style for them, are in
[references/paper-figures.md](references/paper-figures.md).

## When the question is about one number

Sometimes the user does not want a report — they want to know where a figure came from. The record
is the answer, and [references/reading-a-record.md](references/reading-a-record.md) covers
`vqapr show run`, `vqapr show strategy` and `read_strategy_table`.

The four tables every run records, and which question each one answers, are in
[references/result-tables.md](references/result-tables.md). **Cost questions are asked of
`vqapr.fill`** and **compliance questions of `vqapr.monitoring`** — not of a rate read off a venue,
and not of the contract summary.

## Say what the result does not support

A report is not a claim about the future, and several of its numbers rest on choices someone made
earlier: which observation was used as the fill price, what `available_at` was taken to mean,
whether tradability was derived rather than observed. Those limitations travel with the result.
If they were recorded at registration, repeat them here; if the user has not seen them, surface
them before they quote a Sharpe.

**A non-zero `attribution.residual` is a finding, not noise** — it is the part of the NAV change no
marked name explains. Say so rather than rounding past it.

## Stop condition

The user has the answer they asked for, every annualised or risk-adjusted number is stated with
the `periods_per_year` and `risk_free_annual` behind it, and any figure was rendered with a library
they agreed to install.

---

A refusal carries its own status, stage and cause, plus `fix`, `requirement`, `observed` and
`source` — read it rather than looking for it here. Status **500 or 502 is a vqapr defect**: do not
work around it, report it with the envelope.
