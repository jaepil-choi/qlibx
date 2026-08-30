# 038 — One `instruments:` list filters every requirement, so a second dataset's row keys must be enumerated as instruments even when they are not instruments

**Status when filed:** open. Found 2026-08-30 by the first-time-user journey in
`kaist-thesis/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-015**,
`slowed` / `docs`.
**Touches:** `ModelWindow` requirement filtering; `MaterializationSpec.instruments`; the run spec's
`instruments:`; `SKILL.md`'s DataModel paragraph.

## The model

The Fama-French residual arm reads two datasets: `krx-daily` for stock excess returns, and
`kimchi-ff5` for the five factor series. The DataModel contract supports this cleanly —
`requirements()` returns a tuple, so the author returns two `DataRequirement`s and calls
`observations()` on each.

## What the author expected

That `instruments:` in the materialization spec names *what the model is evaluated over and emits
rows for* — the 873 stocks. The factor requirement reads a different dataset whose row keys are
`RMRF`, `SMB`, `HML`, `RMW`, `CMA`. Those are not instruments, not tradable, not in any exchange
listing, and not things the model emits output for.

## What arrived

Zero factor rows:

```
{"status": "short_factor_window", "n_stock_rows": 62572, "n_factor_rows": 0, ...}
```

then a refusal:

```
"observed": "all 1 invocation(s) returned zero rows",
"requirement": "materialization must produce at least one output row",
"fix": "...at least that many rows before the earliest evaluation instant. Otherwise widen the
        requested instruments/evaluation_times, or fix DataModel.compute to emit rows"
```

Adding the five factor ids to `instruments:` — changing nothing else — produced `n_factor_rows: 365`
(73 sessions x 5 factors) and 713 residuals.

So `ModelWindow` filters **every** requirement by the single declared instrument list, across
datasets. A dataset keyed on factor names, macro series, index levels or anything else non-tradable
must have those keys enumerated in `instruments:` alongside the real ones.

## Why it is awkward rather than merely surprising

**One list is doing three jobs:**

1. the universe the model is evaluated over,
2. the row filter applied to every dataset it reads,
3. the closed set of things it may emit — enforced by
   `materialize.output.instrument_unrequested` (see issue 032).

Those three coincide for a single-dataset model and diverge the moment a model reads a second
dataset keyed on something else. Returns plus factors is the most ordinary two-dataset model there
is, so this is the first thing a factor replication hits.

**It also leaks into the run spec.** A simulation's `instruments:` feeds the exchange listing check,
and every instrument there needs a listing or preflight refuses it by name. So the *same* list that
must contain `RMRF` for a materialization must **not** contain it for a run, and the two have to be
maintained separately for what is conceptually one universe.

## The refusal, fairly

It does say *"widen the requested instruments"* — one of three alternatives, alongside lookback
coverage and a broken `compute`. It was not wrong. But it did not say which of the three applied,
and what actually identified the cause was the author's own profiling line (`n_factor_rows: 0` next
to `n_stock_rows: 62572`). Without that instrumentation they would have gone after the lookback
first, since the fix text leads with row coverage.

**Cost:** ~10 minutes, including writing the two-variant experiment to be sure.

## What would close it

The cheap fix is one sentence in the skill's DataModel paragraph: *"a window is filtered by the
declared instruments for every requirement, so a second dataset's keys must be listed too."*

The better fix is a per-requirement instrument scope, so a factor requirement can declare that it is
not instrument-scoped — which would also separate job (2) from jobs (1) and (3), and remove the need
to maintain two divergent copies of one universe.
