# 023 Event-time Account valuation

## Why

Account positions stored a mark price without its observation time, and snapshots treated every
non-null mark as complete. A monitoring callback could therefore publish compliance findings from
an old price while presenting the valuation as current. Account snapshots also lacked the `as_of`
evidence required by the PIT contract.

## Outcome

Every FillBatch and MarkBatch now carries a timezone-aware `as_of`. Account rejects out-of-order
changes, journals their times, checkpoints the latest Account time, and exposes it on snapshots.
Each Position stores `marked_at`. A snapshot evaluated later than any held mark reports `STALE`;
missing marks remain `INCOMPLETE`, and only fully current marks report `COMPLETE`.

State-access evidence preserves Account `as_of` and per-position `marked_at`. Independent
monitoring requests an Account snapshot at the monitoring clock and returns
`ACCOUNT_VALUATION_STALE` before computing or publishing a compliance result. Daily execution may
still proceed from a STALE stored mark because it validates a complete current execution-price
cross-section and uses that cross-section for sizing; it continues to reject missing marks.

## Responsibility and flow

Clock/Flow supplies event time on every Account change. Account owns monotonic state time, mark
freshness, and valuation status. Monitoring consumes that typed status and never decides that an old
mark is acceptable. This keeps time authority out of Position callers and prevents a report layer
from reconstructing freshness from event IDs.

## Alternatives and trade-offs

One Account-level `last_marked_at` was rejected because partial marks can leave held instruments at
different times. Inferring time from the MarkBatch event ID was rejected because IDs are opaque
idempotency identities, not a timestamp schema. Keeping batch time optional was rejected because a
timeless mark cannot support a truthful COMPLETE claim.

Requiring `as_of` is a deliberate public contract change for FillBatch and MarkBatch construction.
It makes previously implicit callback time explicit and portable through checkpoints and evidence.

## Validation

- Account contract: `uv run pytest tests/test_account_kernel.py -p no:cacheprovider --basetemp=<task path> -q`
  -> 8 passed.
- Focused Account, constraint, daily, monitoring, and look-through suite -> 21 passed before the
  final out-of-order test was added; that test passed in the Account contract run above.
- Full suite: `uv run pytest -p no:cacheprovider --basetemp=<task path> -q` -> 87 passed.
- Ruff on the five changed source and three changed test files -> passed.
- `git diff --check` -> passed.

The real-DW monitoring regression rejects a Jan 4 mark at the Jan 5 clock, then succeeds only after
the Jan 5 mark is committed. Account tests also verify timestamp checkpoint round-trip and atomic
rejection of a past change.

## Remaining limitations

Freshness currently means exact mark currency at the evaluation time. Asset-specific tolerances or
session calendars are not inferred by Account; a future profile that permits an older mark must
declare a separate policy and evidence rather than weakening this default status.
