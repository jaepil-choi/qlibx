# 016 Short stored-signal analysis

## Intent

Implement the missing analysis-only path for UC-ERROR-001 and exercise UC-RESEARCH-001 with real
data. A stored signal must be analyzable without creating model, portfolio, optimization, order,
execution, Account, or Strategy Memory stages. Missing realized-return data must fail at the actual
`analysis.run.requirements` path and remain immutable evidence for a later retry.

## Implementation

- `SignalAnalysisRequest` declares one `ComponentRequirement` for the realized-return role, the
  explicit return session, the frozen evaluation time, and optional failure artifact being resolved.
- `AnalysisFlow.analyze_signal` loads the typed stored signal, resolves only that return requirement,
  and reads the selected session through `MaterializeView`. It receives no Account or Memory.
- The pure calculation requires identical signal/return instrument axes, at least two instruments,
  finite values, and non-zero cross-sectional variance. It publishes signal count, Pearson
  information coefficient, and a research-only zero-cost long-short return. Hypothetical weights
  are demeaned signal values normalized to unit gross.
- Missing bindings publish `OperationError` directly from `RequirementResolver`, preserving the
  hierarchical `analysis.run.requirements.<role>` stage. A successful retry can add an immutable
  `resolves_error` dependency while the original failure remains audit-visible.
- `AnalysisResult` now carries dataset access lineage for signal analysis. Existing simulation and
  monitoring results retain an empty default and their schema-1 compatibility.

## Real-data evidence

The scenario publishes A000660 and A005930 2024-01-02 close-to-base returns from
`data/DW/fng_stock_daily_prices.csv` as a typed external stored signal. The first analysis invocation
has no `analysis_return` binding and fails at `analysis.run.requirements.analysis_return`; the only
reusable artifact remains the stored signal.

The retry registers the same audited bounded Parquet as an explicit realized-return capability and
reads the 2024-01-03 session at its close. The produced IC and hypothetical return reconcile to an
independent calculation over those real rows. The analysis artifact links the original failure,
stored signal, return dataset, and config while creating no mutable state.

## Trade-offs

This is cross-sectional one-period research analysis, not an executable short portfolio or an
Account simulation. It does not estimate turnover, cost, capacity, statistical significance, or a
multi-period NAV. Those require separately selected operations and data rather than hidden stages.

The caller explicitly selects the realized-return semantic binding and session. qlibx does not infer
a forward horizon from a field name or assume that a same-day return is economically valid.

## Validation

- UC-ERROR-001/UC-RESEARCH-001, report/monitoring, architecture, and registry -> 7 passed.
- Full pytest -> 76 tests passed in 59.61s.
- Ruff, import smoke, and Git diff check -> passed.
- uv build -> built qlibx 0.1.0 sdist and wheel.
