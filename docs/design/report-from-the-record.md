# The report is read from the record — what the package computes, what a skill draws

**Ruling 2026-09-07, by the owner.** Reporting is not a main feature of vqapr, but a run must be
reportable at the level a paper's table and figure need. The package ships **a Python API only**
(`vqapr.public.strategy_report`, `vqapr.public.run_report`) — no CLI verb, no plotting
dependency. Figures and typeset tables are the agent skill's work, over the values this API
produces. This follows PRD UC-REPORT-001 as written: "vqapr는 table renderer와 machine-readable
renderer를 제공하고 visualization은 제공하지 않는다."

## The evidence

Two 0.4.1 workspaces measured their runs before this API existed, and both re-derived the same
things by hand: `kaist-thesis/vqapr-scenario-testbed/work/analyze.py` (Sharpe, mean, volatility
per strategy; a cumulative-return figure; per-day diagnostics) and
`kwam-enhanced-index/vqapr-enhanced-index-3/measure_ensemble.py` (NAV statistics, active return
against a benchmark book, costs summed from `vqapr.fill`, constraint findings from
`vqapr.monitoring`). The union of the two scripts is the scope here. Every number they produced
this API reproduces exactly on the same records (`measure_ensemble.json`: annualised return,
volatility, Sharpe, drawdown, cost in basis points, breach counts and the worst excess — to the
digit), which is the test that the boundary is drawn in the right place.

## What is computed, from which table

Everything comes from the four tables every run records and the two JSON records. Nothing is
re-priced; a price appears only where the run marked it.

| Section | Source | What |
|---|---|---|
| `performance` | `vqapr.account`, `_ACCOUNT` row | NAV, period returns, drawdown; total and annualised return (geometric and arithmetic), volatility, Sharpe, Sortino, Calmar, max drawdown and its instant, longest drawdown, positive-period share; by year, by month |
| `book` | `vqapr.account`, position rows | held/long/short counts, gross/net/long/short exposure, cash share, max weight, top-five share, HHI, per valuation |
| `attribution` | `vqapr.account` + `vqapr.fill` | per-period P&L by name and side; `residual` = ΔNAV − Σ names; position hit rate; per-name table |
| `trading` | `vqapr.fill` + `vqapr.weight` | one-way realised and intended turnover, costs (commission, tax, bp of notional, share of mean NAV per year, by roster kind), `fill_summary`, holding periods |
| `intent` | `vqapr.weight` against `vqapr.account` | Σ\|realised − intended\| per decision, weight-sign hit rate |
| `compliance` | `vqapr.monitoring` | per constraint: checked / held / within_tolerance / breached / unmeasured, breach share, worst excess, offenders; breached-per-instant series |
| run level | the strategies' reports | headline table, Pearson correlation of period returns on shared instants, each strategy against a benchmark strategy of the same run |

The grid is the valuation instant. A fill belongs to the period whose closing valuation's
`account_version` is the first at or above the fill's — the commit order, not a clock comparison
across tables. When the first valuation already reflects a fill (`account_version > 0`) and the
run's initial positions were empty, the initial cash stands as the first point at the period's
start, so the first day's fills have a period and the cost of entering is not hidden.

## Decisions taken with the ruling

- **Sharpe against a rate the caller gives, zero by default.** The record holds no risk-free rate,
  so none is guessed; `risk_free_annual` is a simple annual rate and the document says which was
  used.
- **Three hit rates, three names.** `positive_period_share` (periods with a positive return),
  `position_hit_rate` (name-periods with a positive P&L), `weight_sign_hit_rate` (intended sign
  against the name's next-period price move). None of them is called "hit ratio".
- **A name's side is its opening side.** A period's P&L on a name is long or short by the sign of
  the quantity at the period's start (or the side it was opened on); a flip inside one period is
  assigned to the opening side. Simple, and the sides sum to the total.
- **Periods per year are inferred and declared.** From the grid's median spacing (252, 52, 12, 4,
  1), reported as `inferred`; a caller's value is reported as `given`.
- **The residual is reported, never absorbed.** Σ names = ΔNAV exactly when every held name was
  marked; where it is not (an unmarked name, cash moving without a fill) the difference is a
  number in the document, per period.
- **Text is exact.** Every number is a `Decimal` and serialises as text; instants keep their zone.

## What is not here, and why

- **A benchmark outside the run.** An index level is not in the record. The enhanced-index
  workspace's answer — run the benchmark as a book of the same run — is the supported one, and
  `run_report(benchmark=...)` measures against it.
- **Factor exposures, IC over a universe.** Prices are recorded for held names only, at valuation
  instants. `vqapr.analysis.signal` remains for a caller who brings a signal table and realised
  returns of their own.
- **Rolling statistics.** Every series is in the document; a rolling window is one line of
  pandas in the renderer.
- **A CLI verb, a Markdown table, a figure.** Declined by the ruling. The skill (`SKILL.md`,
  "Reporting") says how to render the document with the project's own plotting library.

## Where it lives

`src/vqapr/report/`: `document.py` (the pydantic shapes), `measure.py` (rows → sections, pure),
`record.py` (the door through `vqapr.flow.record`). `vqapr.public` exports the two functions
and the two document types. `flow/record.py`'s `resolve_strategy_ref` is the ref resolution
`read_table` already had, given a public name so the report resolves a ref the same way.

Record `163`.
