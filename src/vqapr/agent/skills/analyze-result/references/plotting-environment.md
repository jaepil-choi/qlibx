# The renderer is the project's, and it is probably not installed

## Why this is a conversation and not a step

vqapr ships **no plotting library and no renderer** (PRD §9.4). That is a product decision, not an
omission: `UC-REPORT-001` requires that the same result render through any renderer with the same
underlying values, which it can only guarantee by owning none of them.

The consequence lands here. On a fresh project the libraries a figure needs are absent, and adding
one changes the user's lockfile and their reproducibility. That is their decision.

## The procedure

```bash
uv run python <skill>/scripts/check_plotting_env.py --project-root <project>
```

It reports what is installed, what is missing, which dependency manager the project actually uses
(read from `uv.lock`, `poetry.lock`, `Pipfile.lock`, `environment.yml`, `pyproject.toml`), and the
command that would add exactly what is missing. **It installs nothing.**

Then:

1. **If the project already renders charts with something else** — plotly, altair, an in-house
   wrapper — use that. Do not add a second renderer because this reference names matplotlib.
2. **If something is missing**, ask once: which libraries, why the figure needs them, and the exact
   command the script printed — in a uv project, `uv add matplotlib seaborn`.
3. **Install only after they agree**, with that command, then draw.

## Which library for which figure

| figure | needs |
|---|---|
| lines, bars, areas — NAV, drawdown, exposure, costs, contribution | `matplotlib` |
| heat maps — weights or gaps by name and time, correlation, month-by-year returns | `seaborn` |
| a returns-only tearsheet, when the user asks for that by name | `quantstats` (`--with quantstats`) |

`pandas` and `numpy` carry the frames under all three.

**quantstats recomputes every statistic from the return series it is handed**, with its own
defaults for the year length and the risk-free rate. Pass the report's:

```python
qs.reports.html(returns, rf=0.0, periods_per_year=report.performance.periods_per_year,
                output="tearsheet.html")
```

with `returns` built by the bridge in `paper-figures.md` and its index moved to the run's local
dates (`.tz_convert(zone).tz_localize(None).normalize()`). Given those, its Sharpe, max drawdown
and CAGR equal the report's to six digits on a 1,600-day record. Its numbers are still a second
computation: quote the report's.

## Why the manager matters

Running `pip install` into a uv-managed project writes into an environment the lockfile does not
describe. The next `uv sync` removes it — and from the outside that looks like the install never
happened, which sends the next hour into the wrong question.

## Never add it to vqapr

Not to `pyproject.toml`'s dependencies, not to a group, not "temporarily". A plotting library in
vqapr's dependency tree is the thing §9.4 exists to prevent, and it would be inherited by every
project that installs the package.

## If the user declines

Say that the data is ready, but this project has no tool to visualize it, so the figure cannot be
shown — and stop. Do not draw it some other way: no ASCII chart, no hand-written SVG or HTML, no
install into a different environment. The refusal is the user's decision about their lockfile, and
a workaround overrides it.

A question the user asked in numbers is still answered in numbers; it is the figure that stops.

## What "ready" does not mean

A green check means the imports resolve. It does not mean a backend is configured — a headless
machine may still need `matplotlib.use("Agg")` before saving a file, and the failure there is an
import-time or first-draw error, not a missing package. Save to a file rather than showing a
window.
