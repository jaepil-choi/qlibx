# Academic factor research showcase

Status: superseded by `show_003_academic_exchange_factor_execution`

Last verified: 2026-08-09

Verified against: qlibx 0.1.0, implementations 009, 016, 059, and 060

This showcase preserves the pre-AcademicExchange qlibx factor-research boundary with a real-DW study. A
showcase-local 20-session reversal model uses `QlibxProject.materialize()` to publish one typed
stored-signal artifact at each monthly decision time. `QlibxProject.analyze_signal()` then evaluates
each exact artifact against the following monthly return and preserves PIT dataset lineage.

The generated HTML distinguishes package-owned behavior from showcase-local diagnostics:

- qlibx demonstrates PIT factor materialization and one-period Pearson IC / zero-cost return;
- this runner calculates RankIC, ICIR, quantile spread, turnover, costs, and a multi-period return
index for inspection;
- `AcademicExchange` remains absent, so no Fill, Position, Account, borrow, or collateral behavior
  is claimed.

Its capability verdict is historical and no longer current. Use
`show_003_academic_exchange_factor_execution` for package-owned signed fills, state, and recovery.

The showcase cites implementation records 009, 016, and 059. It reads the real
`data/DW/fng_stock_daily_prices.csv`, but all bounded data, project state, artifacts, CSV summaries,
JSON evidence, and the report are generated only below this showcase's ignored `outputs/` folder.

Reproduce from the repository root:

```powershell
uv run python showcases/show_002_academic_factor_research/run.py
```

After a successful run, open `outputs/report.html`. The study uses a fixed 12-stock universe,
2023-2024 monthly decisions, complete common sessions, and close-to-previous-close returns. These
choices make the workflow deterministic but introduce retrospective selection and survivorship
bias, so the numerical result is not an alpha-quality claim.

The verified run produced 23 monthly factor/analysis pairs. Every qlibx Pearson IC and hypothetical
return reconciled to the independent calculation within `3.7e-16`. The tested reversal definition
was economically weak in this bounded study: mean IC was `-0.1122`, gross cumulative return was
`-15.77%`, and showcase-local net return after a 10 bps turnover charge was `-16.97%`. These values
are reported as observed evidence, not selected or promoted results.
