# 053 -- Methodology, not one-line wrappers

The transform surface had grown by treating common arithmetic as package capability. Thirteen public
operations either duplicated Python/pandas directly or had no authored caller outside their own
tests. `apply_causal` was the sharpest example: it repeated rolling-window slicing in Python and
claimed a practical causal advantage over `Series.rolling(...).apply(...)` without a performance,
cost, or correctness result showing one. show_008 computed every rolling step and discarded all but
the last.

The Fama-French factor testbed exposed the opposite case. Its KOSPI breakpoints were genuinely easy
to implement incorrectly: thresholds are estimated from a named reference market and then applied
to the full KOSPI+KOSDAQ universe. Equal-count quantile bucketing produces plausible-looking but
wrong membership. Linear versus nearest interpolation can also move a name across the breakpoint.
That is a named methodology worth owning.

## What changed

### Removed generic wrappers

Removed `apply_causal`, all five `window_*` reducers, `demean`, `zscore`, `winsorize`,
`quantile_buckets`, `drop_missing`, `require_complete`, `look_through`, and `InstrumentExposure`
from source and the public surface.

- mean, max, stdev, demeaning, z-scoring, clipping and missing-value filtering are direct
  Python/stdlib/pandas expressions;
- the equal-count bucketer and look-through helper had no authored caller across eight showcases
  and two testbeds;
- ETF look-through remains StrategyModel-owned under PRD 8.2: the model computes its chosen
  mapping instead of inheriting package semantics;
- the missing-value doctrine remains canonical: filling with zero is an economic assertion, but a
  dict-comprehension wrapper is not product capability.

`rank` remains because exact Decimal tie averaging is not a one-line operation. `neutralize`
remains because exact weighted regression, rank-deficiency detection and actionable refusal are
both difficult and previously proven easy to get wrong. The weighting family remains because gross
normalization, sign ownership, budget matching and grid-residual settlement are package contracts.

### Added named Fama-French breakpoints

`fama_french_cut_points` computes quantile thresholds from a reference instrument set only.
`fama_french_assign` applies pre-computed thresholds to every supplied instrument. They are split
because cut points are research output worth recording separately from membership.

The contract pins the details that change economics:

- linear interpolation matches the validated pandas/Kimchi replication;
- nearest interpolation must be requested explicitly;
- equality remains in the lower bucket;
- repeated thresholds are valid and may leave a middle bucket empty;
- assignment is threshold-based and deliberately does not promise equal counts.

The testbed now imports these public functions instead of carrying `_quantile` and
`_reference_buckets` private copies.

### Simplified show_008

The low-volatility member and its independent oracle now call `statistics.stdev` on the latest
explicit trailing slice. They no longer calculate and discard earlier rolling results. The
showcase reproduced the same published allocations, costs, fills and final NAV.

## Trade-off

This intentionally removes backward compatibility. A caller using a deleted convenience operation
must use Python, pandas, numpy or direct arithmetic. That makes methodology visible at the model
site and reduces the public vocabulary an agent must search before writing ordinary arithmetic.

The Fama-French API is deliberately not a generic `reference=` argument on `rank`, `zscore`,
`demean` or `winsorize`. Computing parameters from the assigned cross-section is natural for those
operations. Reference-market breakpoints are the special methodology and carry its name.

## Validation

```text
uv run pytest -q tests/transforms tests/boundaries/test_public.py \
  tests/boundaries/test_capability_absence.py \
  tests/acceptance/test_figure_03_neutralization.py
# 63 passed in 51.15s

uv run ruff check src/ tests/ showcases/
# All checks passed!

uv run pytest -q
# 671 passed in 152.01s

uv run python showcases/show_008_alpha_family_ensemble/run.py
# exit 0; 20 dealt fills; commission 71,784.69; sale tax 199,170.20;
# final NAV 999,165,945.11; replicate artifact digests identical

uv build
# dist/vqapr-0.1.0a16.tar.gz and dist/vqapr-0.1.0a16-py3-none-any.whl built
# wheel contains fama_french.py and none of window.py, missing.py, lookthrough.py

# from vqapr-testbed-2
uv run --no-sync python -c "import importlib.metadata as m; from models.factors import FactorPortfolio; from vqapr.public import fama_french_assign, fama_french_cut_points; print(m.version('vqapr')); print(FactorPortfolio('HML').factor)"
# 0.1.0a16 / HML

uv run --no-sync python build_factors.py --factors HML
# 2,096 callbacks; 97 formations; 110,919 membership rows;
# 110,919 allocation rows; 2,368,704 NAV rows

uv run --no-sync python compare_factors.py
# SMB 0.971509; HML 0.972553; RMW 0.941883; CMA 0.917683; MOM 0.984659
```
