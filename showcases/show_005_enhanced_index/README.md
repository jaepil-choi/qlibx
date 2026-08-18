# show_005 — enhanced index over a published alpha

Publishes a signed alpha as an allocation dataset, then constructs a benchmark-relative enhanced
index that consumes both the published alpha and the committed benchmark panel.

Reproduce:

```
uv run python showcases/show_005_enhanced_index/run.py
```

It reads `tests/fixtures/real`, so it runs on a clean checkout with no vendor warehouse.

## What this actually demonstrates

| Claim | How it is shown |
|---|---|
| Publication is a dataset, not a new subsystem | The alpha allocation is published through `publish_run_allocation`, which shares the staging, atomic-exposure and registration body with `materialize` |
| Two allocation panels combine into one construction | The construction reads the published alpha panel **and** the committed benchmark panel each session and forms `desired = bench + s · active` |
| Long-only is emergent | The alpha's minimum weight is `-0.02`. Nothing strips the short leg; `no_short` intersected with a per-name cap does |
| Frozen names survive exactly, or the freeze is refused | 20 of 22 sessions freeze a held name and get it back verbatim. On one session price drift pushed the holding past its cap; the call is made anyway and `optimize`'s own refusal is what releases the freeze, so the guard is exercised rather than duplicated |
| Output is deterministic | Two clean runs produce identical SHA-256 manifests |

## What this does NOT demonstrate

This matters more than the table above, because a showcase that overstates itself is worse than a
smaller one that does not.

- **This is not a `run()`.** There is no `RunDefinition`, no `preflight_run`, no Account, no
  `plan_orders`, and no execution profile. Position sizing and cash are hand-rolled in `main()`. The
  execution spine is exercised by `show_003` and `show_004`; this showcase exercises the
  **construction and publication** path only.
- **Reads are raw file reads, not `DataRequirement` subscriptions.** The published dataset is
  registered in the workspace, but this script reads the parquet directly rather than through a
  point-in-time window, so nothing here proves PIT enforcement. That is proved in
  `tests/flow/test_publish_allocation.py`, which reads a published allocation back through a real
  `DataRequirement` inside a point-in-time window.
- **The cap is inlined here, not the shipped `SingleNameCap`.** `NoShort` is the real shipped
  constraint; the per-name ceiling is recomputed locally because this script has no point-in-time
  window to project through. The acceptance suite drives the shipped constraint for real, projecting `NoShort` and
  `SingleNameCap` through a point-in-time window and intersecting them with `merged_constraint_bounds`,
  so the criteria are not proved against this stand-in.
- **The cash replay is a consistency check, not independent verification.** It recomputes cash from
  the same journal the same loop wrote, so it catches bookkeeping drift within the script and
  nothing more. `show_003` performs the genuinely independent replay against a committed Account.
- **`tracking_error` here is the L2 norm of active weights**, not a realised or forecast tracking
  error. It is recorded as monitoring evidence only and never re-enters the construction.

## Results

| Metric | Value |
|---|---|
| sessions | 22 |
| allocation inputs combined | published `alpha_allocation` + committed `benchmark_weight_daily` |
| alpha minimum weight | −0.020000000000 |
| frozen occurrences | 20 |
| freeze released (holding drifted past its cap) | 1 |
| position changes | 41 (whole units) |
| closing cash | 499,080,100.0000 |
| replayed cash | 499,080,100.0000 (consistency check) |
| active-weight norm | 1.045% → 0.926% |

## Reading the numbers honestly

The active view is **dollar-neutral by construction** and scaled to a 4% gross active budget, so it
moves weight between names without changing the total. That is what makes it an *active* view rather
than a second allocation competing with the benchmark.

The benchmark covers four constituents of a two-hundred-name index, so its weights sum to roughly
`0.549`, not `1`. The uncovered remainder is cash, not an error — the weight-sum invariant is
coverage-scoped for exactly this reason.

`current` is quantized onto the canonical grid before `optimize` is called, which is what a caller
must do: a raw NAV-derived ratio carries 28 significant digits and the bound-exponent guard refuses
it. The refusal itself is proved in `tests/portfolio/test_optimize.py`, not here.

`outputs/` is gitignored.
