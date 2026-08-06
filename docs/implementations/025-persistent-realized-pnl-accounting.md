# 025 Persistent realized-PnL accounting

## Why

Account accumulated realized PnL only on a live Position. A full close then removed that Position
from the sparse map, discarding the amount. Reopening the instrument restarted its PnL at zero,
and Account feedback retained only fill IDs, so neither snapshot nor journal evidence could recover
the path-dependent result. The same close branch silently removed any positive residual quantity at
or below `1e-12`.

## Outcome

Account now owns a cumulative realized-PnL map keyed by instrument independently of its sparse held
Position map. Snapshots, checkpoints, state-access evidence, and journal feedback expose stable,
sorted realized-PnL pairs. A live Position mirrors its instrument's cumulative amount for the
existing Position contract, while closing the Position no longer destroys that state. Checkpoint
restore validates registration, uniqueness, finiteness, and agreement between open Position and
Account PnL values.

Each FillBatch journal entry records the realized-PnL delta produced by that commit. This supports
cursor-based Strategy feedback without introducing a second TradeLedger authority.

## Responsibility and flow

Account applies fills to cloned cash, Position, and realized-PnL maps. A sell calculates its
commit-local delta from average cost, dealt quantity, execution price, and transaction cost; only
after the whole batch validates are all three states and the journal swapped into authority.
Snapshots carry cumulative amounts, while feedback entries carry deltas.

A full close is recognized only at exact zero. A positive residual at or below the numeric dust
threshold returns `POSITION_DUST_UNSUPPORTED`; an oversell of any size returns
`SELL_EXCEEDS_POSITION`. Both leave Account state unchanged.

## Alternatives and trade-offs

Keeping zero-quantity Positions was rejected because the architecture requires a sparse map of
actually held instruments. Reconstructing PnL from fill IDs was rejected because the existing
journal does not contain prices, quantities, or costs. Silently rounding dust to zero was rejected
because that changes an actual quantity and cash/Position correspondence without evidence.

The cumulative map and live Position field duplicate one value for compatibility. Checkpoint
validation and the single Account commit boundary keep them coherent; a future contract revision
could remove the Position mirror after downstream users migrate to the Account-level field.

## Validation

- Focused Account, daily execution, and portfolio-constraint suite -> 21 passed.
- Full suite -> 93 passed.
- Ruff on the three changed source files and Account tests -> passed.
- `git diff --check` -> passed.

Regression coverage closes and reopens one instrument, verifies cumulative and per-commit PnL,
round-trips a checkpoint, and proves that positive dust rejection is atomic.

## Remaining limitations

This is average-cost realized PnL for the current long-only stock/ETF accounting path. Tax-lot
selection, lifecycle cash flows, settlement basis, native short accounting, and portable full Fill
history remain outside current support.
