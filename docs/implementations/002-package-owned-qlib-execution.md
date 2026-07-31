# Package-owned Qlib execution

## Why

The first bounded PnL experiment proved the YAML data boundary but imported the execution runner
from `references/qlib-integration-codex`. That is comparative evidence, not a distributable qlibx
capability.

## Outcome

The proven runner, immutable Parquet artifact catalog, ensemble/reporting functions, and the
minimal Qlib closed-loop backend dependencies are now internal package adapters. The supported
public entry point is `qlibx.execution`; callers do not import the private adapter package.

The backend remains a matched-capitalization compatibility path for Qlib's long-only account. It
submits underlying orders through Qlib and records composite, baseline, and signed active views,
but it does not claim native borrow, margin, recall, or borrow-fee behavior.

## Trade-offs

The internal adapter preserves already-proven execution behavior while qlibx defines a smaller
public API. Only modules required for stored-alpha execution, ensemble, attribution, reporting,
and immutable run storage were brought into the package; unrelated prototype research modules
were not copied.

## Validation

- Ported files were compared line-for-line with the read-only reference after the internal
  import-path rewrite.
- `experiments/exp_003_event_time_qlib_pnl` runs without adding `references/` to `sys.path` and
  records actual SELL/fill/short-position/PnL evidence.
- The final wheel passes all 77 tests on Python 3.10, 3.11, and 3.12 and the real-data showcase on
  Python 3.12 with `pyqlib==0.9.7`.
