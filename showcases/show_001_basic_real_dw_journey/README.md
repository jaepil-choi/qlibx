# Basic real-DW-derived sample journey

Status: current

Last verified: 2026-08-06

Verified against: qlibx 0.1.0, implementation record 018

This showcase proves the opt-in bundled sample through public CLI and Python surfaces. It cites the
production behavior in `docs/implementations/018-opt-in-sample-journey.md`. The bundled four-row
input is a product-owned bounded projection of `data/DW/fng_stock_daily_prices.csv`, not mock market
data or user-owned alpha code.

Reproduce from the repository root:

```powershell
uv run powershell -ExecutionPolicy Bypass -File showcases/show_001_basic_real_dw_journey/run.ps1
```

Generated project state, `result.json`, and `catalog.json` are written only below this showcase's
ignored `outputs/` directory. Re-running is idempotent for the same package version and sample files.
