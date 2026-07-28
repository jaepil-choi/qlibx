# qlibx public extension contracts

Package version: 0.1.0. Instruction schema: 1.

## signal_transform v1

- Workflow location: after a signed signal is computed and before selection/budget/ensemble.
- Input: one bounded `pandas.DataFrame` indexed by its configured datetime, ticker columns.
- Output: a DataFrame with exactly the same axes; missing input remains missing.
- Time boundary: availability was already bounded by the parent decision context; the extension
  cannot load additional data or expand the configured index/availability axes.
- Side effects: none; it cannot mutate a Qlib account or publish directly.
- Validation: deterministic repeat, axes/missingness equality, finite values where input is finite.
- Minimal implementation: `examples/exponential-decay.py`.

## exposure_analyzer v1

- Workflow location: stored-artifact analysis before report composition.
- Input: verified `ArtifactEnvelope` plus its loaded JSON/Parquet payload.
- Output: public `AnalysisSection` with input artifact lineage and serializable data.
- Side effects: none; it does not rerun or publish the artifact producer.
- Minimal implementation: `examples/local-exposure-analyzer.py`.

## report_renderer v1

- Workflow location: after analysis sections have been selected and ordered.
- Input: public `ReportDocument`; calculations are already complete.
- Output: `bytes` or `str`; qlibx owns the final output and manifest write.
- Side effects: none; a report output is not a canonical research artifact.
- Minimal implementation: `examples/local-text-renderer.py`.

Project extensions are trusted code. Contract validation is not a filesystem/network/process
security sandbox. Source digest and contract version are part of frozen invocation identity.
