# VQAPR public execution run

Status: current

This showcase proves the public register → configure → preflight → run spine using only
`vqapr.public` imports. It generates project-local Strategy, Academic Exchange, and Constraint
modules, fingerprints them through `component_ref`, registers all declarations, then runs a typed
`RunDefinition` with an `AccountSnapshot` and `AccountMode`.

Evidence includes:

- real pending intent → due execution → Account mark → monitoring feedback → finalization results;
- an A/B comparison using the same `FrozenRun`: dense physical input has three extra non-selected
  10:00 rows and canonical physical input does not; their complete, unmodified lifecycle traces match;
- explicit finite Strategy, valuation, and monitoring agendas;
- selected exact-time execution pricing and generated component source fingerprints;
- invalid selected-price rejection without workspace mutation.

## Reproduce

From the repository root:

```powershell
uv run python showcases/show_001_execution_input_registration/run.py
```

Inspect:

- `outputs/report.html` — reader-facing run and invariance evidence;
- `outputs/trace.json` — complete public preflight/run values and comparison signatures;
- `outputs/project/components/` — generated public-only component sources;
- `outputs/workspace.yaml` — persisted declarations;
- `outputs/*.parquet` — dense, canonical, and invalid input fixtures.

Environment assumptions: repository `uv` environment, Python 3.12+, DuckDB 1.5+.

Last verified at: 2026-08-16

Verified against: `vqapr-0.1.0+implementation-008-working-tree`
