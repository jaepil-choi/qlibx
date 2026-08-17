# show_005 — enhanced index over a published alpha

Runs the whole chain this milestone exists for, on committed real market data:

```
alpha run (signed, zero cost)  ->  published allocation dataset
                                          |
committed benchmark panel  --------------- +-->  enhanced index (whole-share execution)
```

Reproduce:

```
uv run python showcases/show_005_enhanced_index/run.py
```

It reads `tests/fixtures/real`, so it runs on a clean checkout with no vendor warehouse.

## What it demonstrates

| Claim | How it is shown |
|---|---|
| Publication is a dataset, not a new subsystem | The alpha allocation is published through the same machinery that materialises a DataModel, then read back as an ordinary panel |
| Multi-input subscription works | The enhanced index consumes **two** allocation inputs — the published alpha and the committed benchmark — and combines them |
| Long-only is emergent | The alpha's minimum weight is `-0.02`. Nothing strips the short leg; `no_short` intersected with a single-name cap does |
| Frozen names survive exactly | 21 of 22 sessions freeze a held name; each is returned verbatim, asserted against the quantized input |
| The guard is exercised, not dodged | `current` is a NAV-derived ratio quantized onto the canonical grid before the call — the raw ratio would be refused |
| Accounting is independently checkable | Cash is replayed from the fill journal alone and must match the running balance exactly |
| Output is deterministic | Two clean runs produce identical SHA-256 manifests |

## Results

| Metric | Value |
|---|---|
| sessions | 22 |
| subscribed inputs | `alpha_allocation` + `benchmark_weight_daily` |
| alpha minimum weight | −0.020000000000 |
| frozen occurrences | 21 |
| fills | 40 (whole shares) |
| closing cash | 486,629,800.0000 |
| replayed cash | 486,629,800.0000 (exact match) |
| tracking error | 1.045% → 0.642% |

## Reading the numbers honestly

The active view is **dollar-neutral by construction** and scaled to a 4% gross active budget, so it
moves weight between names without changing the total. That is what makes it an *active* view rather
than a second allocation competing with the benchmark.

Tracking error is computed **after** each decision and recorded as monitoring evidence only. It never
enters the construction, because a portfolio-level quadratic has no representation in per-instrument
constraint bounds. Constraining it ex ante is deliberately out of scope for this milestone.

The benchmark covers four constituents of a two-hundred-name index, so its weights sum to roughly
`0.549`, not `1`. The uncovered remainder is cash, not an error — the weight-sum invariant is
coverage-scoped for exactly this reason.

`outputs/` is gitignored.
