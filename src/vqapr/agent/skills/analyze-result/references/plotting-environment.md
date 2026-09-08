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
2. **If something is missing**, tell the user what, why it is needed for the figure they asked for,
   and show the exact command. Then ask.
3. **Install only after they agree**, with the command the script printed for their manager.

## Why the manager matters

Running `pip install` into a uv-managed project writes into an environment the lockfile does not
describe. The next `uv sync` removes it — and from the outside that looks like the install never
happened, which sends the next hour into the wrong question.

## Never add it to vqapr

Not to `pyproject.toml`'s dependencies, not to a group, not "temporarily". A plotting library in
vqapr's dependency tree is the thing §9.4 exists to prevent, and it would be inherited by every
project that installs the package.

## If the user declines

Give them the numbers. `headline`, `by_year` and the compliance counts are tables, and a markdown
table in the terminal answers most questions a chart would. Say what the figure would have shown
and leave the offer open.

## What "ready" does not mean

A green check means the imports resolve. It does not mean a backend is configured — a headless
machine may still need `matplotlib.use("Agg")` before saving a file, and the failure there is an
import-time or first-draw error, not a missing package. Save to a file rather than showing a
window.
