# 036 Preserve operation purity and failure classification

## Intent

Ensemble construction executed the same pure operation once as a compatibility probe and again
through `ResearchFlow`, while retaining the first result in mutable instance fields. Three flows
also caught data reads and pure calculation under one broad exception boundary, causing unexpected
calculation defects to be reported as data failures. The empty-account mark branch mutated run
evidence before its artifact publication succeeded.

## Observable outcome

Ensemble inputs are reduced to one immutable `_EnsembleComputation` during construction. The
operation `run()` only returns the frozen draft and is invoked once by `ResearchFlow`; evidence reads
the same frozen computation.

Constraint adjustment and validation, constraint monitoring, and signal analysis now materialize
all data before entering a separate pure-compute boundary. Unexpected calculation defects return
`CONSTRAINT_COMPUTE_FAILED`, `MONITORING_COMPUTE_FAILED`, or `ANALYSIS_COMPUTE_FAILED` with a
`.compute` stage and `commit_status=NONE`. Data-materialization failures retain their existing
`*_DATA_READ_FAILED` codes and `.data` stages.

An empty holdings mark is appended to in-memory run evidence only after the `mark_result` artifact
has been published successfully.

## Responsibilities and flow

- `EnsembleStrategyOperation.__init__` validates member state compatibility and calculates the
  immutable draft, contribution ledger, gross values, and net exposure once.
- `CompositionFlow` no longer calls `run(object())`; `ResearchFlow` is the sole invocation path.
- `ConstraintFlow`, `MonitoringFlow`, and `AnalysisFlow` freeze benchmark, account, access, signal,
  and return inputs in data-read blocks, then call pure functions in compute blocks.
- Known domain exceptions keep their specific typed codes. Only unexpected compute exceptions are
  translated to the new family codes.
- `DailyExecutionFlow._on_mark` treats successful publication as the boundary for adding empty mark
  evidence to the run result.

## Alternatives and trade-offs

Leaving the compatibility probe and merely clearing mutable fields was rejected because it would
still execute an operation twice and could hide future side effects. Recomputing inside `evidence()`
was rejected because evidence could diverge from the published strategy result.

A shared catch-all exception translator was not introduced. The data and compute stages have
different inputs and recovery semantics, so explicit local boundaries make misclassification
harder to reintroduce.

The new unexpected-compute codes do not prescribe retry. Repeating an identical frozen input on the
same implementation is diagnostic reproduction, not recovery; the bundled error-recovery guide now
requires preserving the failure and reporting the diagnostic until code or the input contract
changes.

## Validation

```
.venv/Scripts/python.exe -m pytest tests/test_public_constraints.py tests/test_public_daily.py tests/acceptance/test_analysis_scenarios.py tests/acceptance/test_research_scenarios.py -q -p no:cacheprovider --basetemp=.agent/runs/pytest-c5-targeted-final-019fd96d
-> 24 passed in 85.25s

.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp=.agent/runs/pytest-c5-full-019fd96d
-> 165 passed in 381.63s

.venv/Scripts/python.exe -m ruff check .
-> All checks passed!

git diff --check
-> clean
```

The regression tests count `EnsembleStrategyOperation.run` calls, inject unexpected defects on both
sides of a data/compute boundary, and observe the empty mark list at the publication call.

## Remaining limitations

- Known domain computation failures retain their existing specific codes; the new family codes are
  reserved for unexpected defects.
- The flows still materialize DataFrames in orchestration. Moving table conversion into dedicated
  adapters is outside this remediation.
- Failure artifacts remain append-only diagnostics and are not automatically retried.
