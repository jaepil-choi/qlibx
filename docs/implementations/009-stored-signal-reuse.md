# 009 Stored signal reuse

## Intent

Implement UC-SIGNAL-002 and the model-output side of UC-ARTIFACT-001. A documented signal payload
created outside qlibx must round-trip through typed validation and be reusable by multiple Strategy
operations without importing or rerunning its producer.

## Implementation

- StoredSignalResult defines a versioned signal semantic, observation time, and unique
  instrument/value axis. Unknown versions and invalid duplicate keys are rejected by the existing
  ArtifactContract loader.
- CompositionFlow loads a stored signal by typed contract and invokes a Strategy operation with an
  explicit artifact dependency. Producer implementation is neither imported nor called.
- LONG_SHORT_EXTREMES and LONG_ONLY_MAX are distinct weighting semantics. Both publish normal
  StrategyResult artifacts and keep independent invocation/config identities.

## Real-data evidence

The acceptance extracts the 2024-01-02 close-to-base return for A005930 and A000660 from the
bounded Parquet projection of the unchanged DW CSV rows. It serializes that characteristic as if
from an external process and imports it once through `import_model_bytes`.

- The long-short consumer produces A000660 -0.5 and A005930 +0.5.
- The long-only consumer produces A005930 +1.0.
- Both StrategyResult envelopes depend on the exact same imported signal artifact with
  `stored_signal` lineage, while their weighting diagnostics and invocation identities differ.

## Trade-offs

The first stored signal axis is one scalar per instrument at one observation time. Panels, factor
exposures, risk estimates, and multi-horizon predictions require separate semantic contracts rather
than overloading this payload.

## Validation

- Real DW stored-signal round-trip acceptance: passed.
- Full pytest: 49 passed.
- Ruff and git diff --check: passed.
- `uv build`: built qlibx 0.1.0 sdist and wheel.
