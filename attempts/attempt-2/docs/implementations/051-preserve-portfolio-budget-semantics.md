# Preserve portfolio budget semantics

## Intent

Portfolio construction must preserve the source Strategy's gross utilization and residual cash unless the consumer explicitly requests renormalization.

## Observable outcome

The request declares consumer budget mode and normalization policy. Result schema v2 records source and requested budget semantics, dropped weights and gross, and any renormalization scale. A fixed consumer that forbids the resulting residual fails with `CONSTRUCTION_FIXED_BUDGET_INCOMPATIBLE`.

## Responsibilities and flow

The portfolio flow carries `budget_mode` and `target_gross` from the frozen Strategy result. Construction removes unsupported weights, preserves utilization by default, and scales only under `renormalize_to_requested_budget`. The v1 payload model remains available for exact reads.

## Alternatives and trade-offs

Implicit long-only normalization was rejected because it converts removed short exposure into a different economic target. Explicit normalization remains available for consumers that intentionally accept that transformation.

## Validation

The corrected `UC-PORTFOLIO-001` oracle expects 0.5 gross and 0.5 residual. `uv run python -m pytest tests -q -p no:cacheprovider` passed 247 tests in 114.80s; `uv run ruff check .`, the ignored `import qlibx` smoke script, and `uv build` also passed.
