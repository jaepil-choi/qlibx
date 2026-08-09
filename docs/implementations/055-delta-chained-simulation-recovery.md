# Delta-chained simulation recovery

## Intent

Recovery writes must stop serializing completed account and event history at every session while preserving Account replay invariants and compatibility with active v1 runs.

## Observable outcome

Recovery schema v2 stores the previous artifact ID, latest live account state, and journal, trace, and completed-decision deltas. Restore validates cycles, sequence gaps, account-version gaps, and identity mismatches, then reconstructs a complete `AccountCheckpoint`. A v1 point can anchor a new v2 chain; final simulation checkpoints remain complete.

## Responsibilities and flow

Daily flow tracks durable cursors after each successful point. Restore walks backward from the latest point, validates each link, stops at the initial state or a v1 anchor, and replays deltas forward through `Account.from_checkpoint` validation.

## Alternatives and trade-offs

A base cursor plus cumulative `applied_events` was rejected because completed history would still grow. Pruning and compaction remain out of scope, so a long chain still costs linear reads at resume time.

## Validation

`exp_002_recovery_write_scaling` records the concluded v1 baseline and v2 acceptance probe; v2 100/50 total bytes are 1.99x and the last point is 940/937 bytes. `uv run python -m pytest tests -q -p no:cacheprovider` passed 247 tests in 114.80s, including v1-to-v2 bridge, sequence-gap, recovery, and crash-matrix regressions. `uv run ruff check .`, the ignored `import qlibx` smoke script, and `uv build` also passed.
