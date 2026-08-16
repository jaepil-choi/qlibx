# VQAPR execution input registration

Status: current

This showcase demonstrates execution-input registration plus the finite operation-agenda contract
superseding implementation record 006:

- observation parquet registration through `vqapr.public.register_dataset`;
- execution parquet registration through `vqapr.public.register_execution_input`;
- separate observation and exact-time execution contracts;
- independent Strategy, valuation, and monitoring agenda registration;
- callback occurrences supplied only by explicit finite agendas;
- passive execution rows that do not manufacture callback occurrences;
- selected execution-price validation without fallback;
- failed invalid-price registration without workspace mutation.

It does **not** demonstrate orders, fills, Account mutation, valuation, or portfolio performance.

## Reproduce

From the repository root:

```powershell
uv run python showcases/show_001_execution_input_registration/run.py
```

Inspect:

- `outputs/report.html` — human-readable evidence;
- `outputs/trace.json` — machine-readable outcomes;
- `outputs/workspace.yaml` — persisted declarations;
- `outputs/observation_price_daily.parquet` — PIT observation fixture;
- `outputs/execution_krx_daily.parquet` — exact-time execution fixture;
- `outputs/invalid_execution_price.parquet` — rejected price fixture.

Environment assumptions: repository `uv` environment, Python 3.12+, DuckDB 1.5+.

Last verified at: 2026-08-16

Verified against: `vqapr-0.1.0+implementation-008-working-tree`
