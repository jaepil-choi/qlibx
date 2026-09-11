---
name: analyze-result
description: Reads a finished vqapr run's records and turns them into answers, tables, and publication-quality figures — returns, costs, turnover, exposures, intended-versus-realized diagnostics, and attribution. Asks before adding plotting libraries (matplotlib, seaborn) to the user's project with uv add, and stops the figure if they decline. Use when the user asks how a backtest performed, wants a chart, plot, table, tearsheet, or paper figure, wants to compare runs or strategies, or asks where a number in a result came from.
---

# Read a finished vqapr run

## Invoke the CLI through the active environment

Installing a console script into a virtual environment does not put it on the global shell PATH.
Use one launcher consistently:

- activated environment: `vqapr --help`
- uv-managed project: `uv run vqapr --help`

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed; the environment
is simply not activated. Apply the same prefix to every command below.

## Numbers from the report, panels from the tables

`strategy_report` and `run_report` read a finished record back and compute, once, what a paper's
tables need. Quote those numbers; recomputing one from the raw tables means computing it
differently.

```python
from decimal import Decimal
from pathlib import Path
from vqapr.public import run_report, strategy_report

store = Path(".vqapr")                       # the `store_root` `vqapr run` printed
one = strategy_report(store, "reversal")     # the run's only strategy, or "<id>" / "<id>@<fp8>"
versions = run_report(store, "reversal", risk_free_annual=Decimal("0.03"))  # every finished record of the run
one.as_record()                              # JSON-ready: Decimal as text, instants with offset
```

**The report is library calls** — the values are the package's and the picture is this skill's.

**To hand a record over as files — to a user, a spreadsheet, a comparison script — run
`vqapr export`, and do not write an exporter:**

```bash
vqapr export <run-id>/<strategy-id>@<fp8> --out outputs/
```

It writes `nav.csv` (the report's own NAV series, one row per valuation, with the local `date`),
`holdings.csv`, `fills.csv`, `weights.csv`, each table the strategy formed under `tables/`, and
`report.json`, every number exact decimal text. Three agents each wrote their own exporter
instead, and each broke on the way — on which `vqapr.account` rows carry the NAV, on types, on
JSON keys.

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

The sections are totals: `book` sums the weights at each instant, `attribution.by_instrument` sums
each name's P&L over the run. **The panels under them — each name's weight at each instant, each
name's P&L in each period, each fill's cost and price — are already rows in the tables.** A weight
heat map, per-name contribution lines, costs per rebalance, refusals by reason and fill price
against the price at the decision are built from them in
[references/panels-from-tables.md](references/panels-from-tables.md), and each is reconciled with
the report before it is drawn.

A run holds one strategy, so a `RunReport` lines up **that strategy's records — its tweaks —
side by side**: `headline` (one row per record), `correlation` of period returns over the instants
they share, and `relative` against the record you name as `benchmark`. Two different strategies
live in two runs: compare them with a `strategy_report` each. An index level is not in the record
and is not invented.

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
(PRD §9.4): the picture belongs to the project, and so do the libraries that draw it — which on a
fresh project are not installed. Check before writing any plotting code:

```bash
uv run python <skill>/scripts/check_plotting_env.py --project-root <project>
```

`<skill>` is the directory this `SKILL.md` is in. The script reports what is missing and prints the
command that adds exactly that — `uv add ...` in a uv project — and **installs nothing**.

Then:

1. If the project already renders charts with something else, use that. Do not add a second one.
2. If something is missing, **ask once**, naming the libraries, what they are for, and the command:
   *"To draw this I need to add matplotlib and seaborn to this project with
   `uv add matplotlib seaborn`. Shall I?"* Adding a dependency changes their lockfile.
3. **Yes:** run that command, then draw.
4. **No:** say that the data is ready but this project has no tool to visualize it, so the figure
   cannot be shown — and stop there. Do not substitute ASCII charts, hand-written SVG or HTML, or an
   install somewhere the user did not agree to.

Never add a plotting library to vqapr itself.

Which library each kind of figure needs, and the traps in them, are in
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

The user has the answer they asked for, and every annualised or risk-adjusted number is stated
with the `periods_per_year` and `risk_free_annual` behind it. A figure was either rendered with
libraries the user agreed to add, or — when they declined — they were told the data is ready and
there is no tool to show it, and the figure stopped there.

---

A refusal carries its own status, stage and cause, plus `fix`, `requirement`, `observed` and
`source` — read it rather than looking for it here. Status **500 is a vqapr defect**: do not work
around it, report it with the envelope. **502 is your own code raising** — `cause.origin` is
`"user"` and `cause.where` is your file and line; fix the component. **503 is the machine** — retry
unchanged.
