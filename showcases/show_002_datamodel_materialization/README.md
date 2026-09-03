# VQAPR DataModel materialization

Status: current

This showcase demonstrates the production DataModel path:

- register an actual PIT observation parquet as `price_daily`;
- register a project-local, fingerprinted `DataModel`;
- read only declared `RowsLookback(2)` observations through `ModelWindow`;
- compute value rows without producer-controlled `available_at`;
- package-stamp and publish a validated derived parquet as `reversal_features`;
- consume that derived dataset through a second ordinary `DataRequirement`;
- reject timestamp forgery without changing the workspace or publishing partial output.

It does **not** demonstrate StrategyModel callbacks, execution inputs, orders, fills, Account
mutation, valuation, or performance.

## Reproduce

From the repository root:

```powershell
uv run python showcases/show_002_datamodel_materialization/run.py
```

Inspect:

- `outputs/report.html` — human-readable evidence;
- `outputs/trace.json` — machine-readable assertions, rows, lineage, and hashes;
- `outputs/workspace.yaml` — persisted raw, derived, and component declarations;
- `outputs/price_daily.parquet` — input including deliberately future-dated `999` values;
- `outputs/project/.vqapr/materialized/reversal_features.parquet` — first derived dataset;
- `outputs/project/.vqapr/materialized/reversal_features.lineage.json` — exact access evidence;
- `outputs/project/.vqapr/materialized/absolute_scores.parquet` — derived-dataset reread result.

Environment assumptions: repository `uv` environment, Python 3.12+, DuckDB 1.5+, PyArrow 25+.

Last verified at: 2026-09-03

Verified against: `vqapr-0.4.0`
