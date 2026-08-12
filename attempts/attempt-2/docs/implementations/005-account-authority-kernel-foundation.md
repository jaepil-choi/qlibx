# 005 Account authority and kernel foundation

## Why

Closed-loop callbacks need an authoritative mutation boundary before orchestration is added.
Otherwise callback order, Exchange calculation, and actual Account state can become coupled and
partial failures can leak into the next Strategy decision.

## Outcome

Account now owns cash, Position average cost, realized PnL, marks, NAV status, applied event IDs,
version, journal, and feedback cursor. FillBatch and MarkBatch commit with expected-version CAS,
event idempotency, and all-or-nothing validation. StrategyMemoryStore is a separate CAS authority.
BacktestClock can queue immutable events and returns same-time handlers in deterministic priority
order without invoking callbacks itself.

## Responsibility and flow

Exchange still returns pure candidate Fill rows. Flow will be the only caller of Account.commit.
The Account applies a cloned candidate state and swaps it into authority only after every Fill or
Mark validates. Kernel owns timestamp and handler order only; business callbacks remain a Flow
responsibility. Fill and Side moved to the dependency-neutral domain module so Account does not
import the execution calculation layer.

## Alternatives and trade-offs

This is not full CQRS or Event Sourcing: Account stores current state and a bounded authoritative
journal. Marks may be partial, producing INCOMPLETE valuation rather than pretending NAV is
complete. Closed positions are removed from the sparse position map; full realized-PnL reporting
will consume the fill journal in the analysis slice.

## Validation

- Full pytest with task basetemp: 46 passed.
- Ruff and git diff check: passed.
- uv build: built qlibx-0.1.0 sdist and wheel.
- Tests cover duplicate/stale/partial-failure atomicity, mark completeness, feedback cursors,
  Memory CAS, and MARK-before-MONITOR handler priority.

## Remaining limitations

M4 is not complete. Decision, execution, mark, monitor callbacks, checkpoint finalization, and the
two-decision actual-feedback journey still need to be connected around these authorities.
