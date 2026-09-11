# Tables and figures for a paper

## Contents

- The bridge from a report to a frame
- What a paper expects, and where it comes from
- House style
- What to put in the caption

vqapr computes the values and **ships no plotting library and no renderer**, on purpose (PRD
§9.4, `UC-REPORT-001`): the requirement is that the values are renderer-independent, not that
vqapr picks one. Render in the project with whatever it already uses — `pandas` + `matplotlib` is
the usual pair. **Add them to the project, never to vqapr**, and only after the user agrees
(`scripts/check_plotting_env.py`).

## The bridge

Every series in the document is `instants` beside `values`:

```python
import pandas as pd

def series(s) -> pd.Series:
    return pd.Series(s.values, index=pd.to_datetime(s.instants, utc=True)).astype(float)
```

`utc=True` is not optional: a report's opening instant carries a fixed offset while the rest carry
the run's zone, and `pd.DatetimeIndex` refuses the mix.

`.astype(float)` is deliberate and belongs only here, at the rendering edge. The document's exact
`Decimal` text is what goes into the replication package; a figure needs a float.

## What a paper expects, and where it comes from

**Table 1 — headline.** One row per strategy: annualised return, volatility, Sharpe, max drawdown,
turnover, cost, breaches. `run_report(...).headline`. Round for the table only; keep the document's
exact text for the appendix.

**Table 2 — by year.** `performance.by_year` per strategy: total return, volatility, Sharpe, max
drawdown. Add `relative` columns when a benchmark book is in the run.

**Table 3 — execution.** `trading.costs`, `trading.fills`, `intent.mean_gap`, and
`annualized_realized_turnover` beside `annualized_intended_turnover` — that second pair is the size
of what did not execute, and it is usually the most interesting row on the page.

**Table 4 — compliance.** `compliance.rules`: checked / held / within tolerance / breached,
worst excess, top offenders.

**Figure 1 — cumulative return with drawdown beneath.** `performance.nav` normalised to 1 (or
cumulative `returns`), one line per strategy; `performance.drawdown` as a filled area below, on a
shared x axis.

```python
fig, (top, bottom) = plt.subplots(
    2, 1, sharex=True, figsize=(7, 4.5), height_ratios=[3, 1]
)
for name, report in every.strategies.items():
    nav = series(report.performance.nav)
    top.plot(nav.index, nav / nav.iloc[0], label=name)
    bottom.fill_between(
        series(report.performance.drawdown).index,
        series(report.performance.drawdown),
        0,
        alpha=0.3,
    )
top.legend(loc="upper left", frameon=False)
top.set_ylabel("cumulative (x)")
bottom.set_ylabel("drawdown (%)")
for ax in (top, bottom):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linewidth=0.4, alpha=0.5)
bottom.axhline(0, linewidth=0.8, color="black")
fig.savefig("figure1.pdf", bbox_inches="tight")
```

**Figure 2 — the book over time.** `book.gross_exposure`, `net_exposure`, `held` — three small
panels on one x axis.

**Figure 3 — correlation.** `run_report(...).correlation.values` as a heat map with the value
printed in each cell.

## House style

- serif, or the journal's font
- one column ≈ 3.3 in wide, two columns ≈ 7 in
- 300 dpi PNG for review, PDF for submission
- no top and right spines; a light horizontal grid only
- a legend inside the axes, or a caption
- colour that survives greyscale — vary line style, not only hue
- draw the zero line
- label axes with units (`%`, `× NAV/yr`)

## What to put in the caption

**`periods_per_year` and `risk_free_annual`.** The document carries both, one of them is usually
inferred, and a reader will ask. A Sharpe printed without its risk-free rate is not reproducible.

If the result carries limitations from registration — a derived tradability rule, an assumed
publication lag, a fill price whose observation time is not in the data — the caption or the
methods section is where they belong. They do not stop being true because the figure looks clean.
