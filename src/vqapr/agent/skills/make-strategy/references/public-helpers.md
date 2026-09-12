# `vqapr.public` — check it before writing portfolio arithmetic

About 160 names, and **the CLI help does not list them.**

```python
import vqapr.public as public
[name for name in dir(public) if not name.startswith("_")]
```

A first-time journey hand-rolled 30/70 breakpoints and a bucket assignment that were already in
the package, and four of that journey's findings turned out to be answerable from this one module.
Listing it costs one line.

## Three families worth knowing by name

### Fama-French sorting

`fama_french_cut_points(values, reference=..., fractions=...)` returns quantile thresholds
estimated **from the reference subset only**; `fama_french_assign(values, thresholds=...,
labels=...)` maps names onto buckets.

`fractions=(Decimal("0.3"), Decimal("0.7"))` is the standard 2×3 sort.

**Interpolation is explicit because it moves portfolio membership.** `linear` is the
pandas/numpy default and matches the validated Korean replication behind these helpers; `nearest`
is the alternative. Neither is a detail — the name on the boundary changes bucket.

### Weighting and neutralization

`equal_weight`, `proportional_weight`, `signal_weight`, `neutralize`, `optimize`, `rescale`,
`net_members`.

Each has a matching typed refusal — `WeightingRefusal`, `NeutralizationRefusal`,
`OptimizeRefusal` — so a book that cannot be built says why rather than returning something
plausible.

### Measurement

`information_coefficient`, `rank_information_coefficient`, `rank`, `nav_series`, `returns`,
`drawdown`, `hit_rate`, `decay`.

These are library calls, not CLI verbs. Use them inside `decide()`, or in your own preparation
code before a run.

## The box: `no_short`, `single_name_cap`, `intersect`

The limits a strategy builds inside are its own (a constraint is not an extension point). Three
pure functions, each returning `(lower, upper)` — a bound per name on each side — which is what
`optimize(lower=..., upper=...)` takes:

```python
names = tuple(sorted(call.window.instruments))
lower, upper = intersect(no_short(names), single_name_cap(names, benchmark, Decimal("0.10")))
```

`single_name_cap` needs the index weight per name: read it through your own `inputs()` and
validate it (`validate_allocation`) before it becomes a bound. Whether the book *actually* stayed
inside a limit is a different question, on a different clock — the `make-compliance` skill.

## What these helpers deliberately will not do

They are pure, and the constraints are what keep them from becoming a second, invisible strategy:

- **No access to registered data, account state, the clock or the execution profile.** Every value
  they need arrives as an argument. If sizing needs an external panel — market cap, say — the
  caller passes it, so that data goes through the strategy's declared requirements and lands in
  the result's lineage.
- **They do not decide a budget.** An under-allocated result is not topped up.
- **They do not handle missing values quietly.** A required side input that is absent fails
  *before* the calculation rather than dropping the name and renormalising the rest.
- **Same input, same output.** They do not know the run id, the decision time or the account
  version, so they cannot assemble an executable intent. That assembly, and its lineage, is the
  StrategyModel's.

Resolving missing values in the research result itself is not the weighting helper's job. There is
a separate explicit helper for it, and it **returns which names were excluded and why** so the
exclusion reaches the result's evidence instead of vanishing.

## One-liners are deliberately absent

Only calculations that are hard or easy to get wrong are built in. A `pandas`/`numpy` one-liner is
not wrapped in a package API, so not finding something here often means it is a one-liner rather
than that it is missing.
