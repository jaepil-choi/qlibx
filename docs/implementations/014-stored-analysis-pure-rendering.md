# 014 Stored analysis and pure rendering

## Intent

Implement UC-REPORT-001 and UC-MONITOR-001 with one calculation boundary. Analysis must load typed
stored evidence and publish durable values. Table, chart, and machine renderers must consume only
that analysis artifact and preserve its values rather than recalculating from Account or execution
state.

## Implementation

- Portable AnalysisResult stores ordered metrics, typed monitoring records, source artifact IDs,
  limitations, state semantics, and a fingerprint over metrics and records.
- AnalysisFlow loads SimulationCheckpoint, ExecutionEvidence, constraint monitoring results, and
  OperationError payloads through explicit versioned contracts.
- Simulation analysis calculates total return, total cost, gross/net physical exposure, fill count,
  failure count, and Account journal event count once from the stored execution/checkpoint inputs.
- Monitoring analysis converts actual-account findings and missing-input errors to different
  record types. Intended target artifacts are not accepted as inputs.
- Report rendering loads only AnalysisResult. Every renderer copies the same metrics, records, and
  fingerprint into ReportResult. Table and chart content are presentation encodings; machine
  content is the stored analysis payload.
- Analysis and report artifacts have explicit lineage to their stored inputs and renderer config.
  Neither flow receives mutable Account or Strategy Memory authority.

## Real-data evidence

UC-REPORT-001 runs the existing real-DW daily closed loop once, then analyzes its stored
simulation_checkpoint and execution_result artifacts. The accepted total cost and return reconcile
to the original committed fills and final NAV. Table, chart, and machine reports share one analysis
artifact and exactly equal metrics, records, and value fingerprint.

UC-MONITOR-001 uses the real K200 constraint binding and committed A005930 Account. The stored
monitoring result has one single-name breach and one passing no-short finding. A separate unresolved
requirement produces an immutable OperationError. Monitoring analysis reports one breach and one
missing input as distinct records, carries actual-account state identity only, and does not depend
on decision targets.

## Trade-offs

The first simulation metric set is intentionally small. It does not claim advanced attribution,
risk statistics, or actual settlement accounting. New statistics can extend the AnalysisResult
contract, but renderer implementations still cannot load raw execution inputs.

Count metrics use numeric values so table, chart, and machine renderers share one value contract.
Their unit is explicitly count, preventing a renderer from inferring display semantics from the
number alone.

## Validation

- Architecture, registry, and real-data reporting suite -> 6 passed.
- Full pytest -> 74 tests passed.
- Ruff, git diff check, and public import smoke -> passed.
- uv build -> built qlibx 0.1.0 sdist and wheel.
