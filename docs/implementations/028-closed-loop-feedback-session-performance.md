# 028 Closed-loop feedback and session performance

## Why

The daily engine exposed a committed AccountSnapshot and feedback cursor to Strategy, but not the
FillBatch and MarkBatch payloads behind that cursor. The existing adaptive acceptance therefore
proved only that a cursor advanced; a Strategy could not inspect the actual fills, transaction
costs, realized outcomes, or marks it was said to consume.

The engine also had final analysis metrics but no immutable per-session record that a subsequent
Strategy could read. Historical qlib-integration-codex work demonstrated the need for PIT signals,
enhanced-index targets, execution feedback, daily return/cost/turnover, and adaptive state. Those
implementations are scenario sources only. Their APIs, order quantities, PnL, and accounting rules
are not qlibx acceptance oracles.

## Observable outcome

A daily Strategy can now read a bounded immutable Account feedback window after its committed
Strategy Memory cursor. The returned entries contain the exact committed Fill and Mark payloads.
StrategyResult lineage records the consumed cursor range, event types, fill IDs, and marked
instruments. A Memory update advances only to the cursor actually read.

After every daily mark, Flow publishes one SessionPerformanceEvidence derived from qlibx committed
execution and mark evidence. The next Strategy may explicitly read the latest completed record,
and its artifact ID is added to StrategyResult dependencies.

A user-authored long-only peer-momentum enhanced-index acceptance scenario runs two decisions over
real DW stock closes, audited K200 weights, and real KODEX 200 closes. It uses PIT observations,
actual Account feedback, latest completed session performance, and committed Strategy Memory. Its
stock targets obey the current single-name cap, its residual is allocated to the ETF, and repeated
runs are deterministic. No Qlib numeric parity is asserted.

## Responsibilities and flow

- Account remains the sole actual-state authority. JournalEntry now retains the Fill or Mark payload
  that produced each committed cursor; AccountFeedback is an immutable bounded view with explicit
  account ID, after cursor, and next cursor.
- DailyExecutionFlow calculates the feedback window from Strategy Memory. If the configured window
  cannot reach the current Account cursor, it fails before Strategy invocation instead of silently
  providing partial feedback.
- StrategyView exposes Account feedback without exposing mutable Account methods. ResearchFlow
  records feedback access in StrategyResult and its state lineage.
- Memory planning validates Account identity and the exact consumed cursor range. Initialization
  may consume an empty 0-to-0 window; later updates require an advanced feedback cursor.
- SessionPerformanceEvidence is derived after the committed mark and depends on the exact mark and
  execution artifacts. It is reporting/feedback evidence, not a second Account authority.
- Daily recovery hydration reloads session-performance artifacts by identity, so resumed and
  uninterrupted result collections remain identical.
- StrategyView exposes only the latest completed session-performance artifact. A decision at a
  session close runs before that close's execution, mark, and monitor callbacks, so it cannot read
  same-session or future performance.

For positive opening NAV, qlibx defines the daily values as:

- portfolio_return = closing_nav / opening_nav - 1
- turnover = gross actual trade value / opening_nav
- transaction_cost_rate = actual Fill transaction cost / opening_nav
- gross_return = portfolio_return + transaction_cost_rate

Opening NAV is the Account NAV before the session's first execution, or before the mark when there
is no execution. Closing NAV is the Account NAV after the committed mark. Current scope has no
external cash flow, so no subscription/redemption adjustment is applied.

## Alternatives and trade-offs

Storing portfolio metrics as mutable Account history was rejected because it would mix actual-state
authority with analysis, a responsibility explicitly rejected by the architecture. Passing the
Account aggregate itself to Strategy was also rejected because it would expose mutation methods.

Using the latest Account cursor as the Memory cursor was rejected. It can claim feedback was
consumed even when Strategy never read it. The new cursor comes from the recorded feedback access.

Silently truncating a large feedback backlog was rejected because Strategy would see the latest
AccountSnapshot while receiving only an older subset of events. The current profile fails
explicitly when feedback_entry_limit is insufficient.

Qlib report fields and stored Qlib output tables were not used as calculation oracles. The
historical peer-momentum shape was re-expressed as a bounded user Strategy using qlibx timing,
cost, Account, evidence, and constraint semantics.

## Validation

- Historical strategy capability catalog: 1 passed.
- Account, Architecture, execution, and durable recovery regression for bounded feedback:
  30 passed in 134.64 seconds.
- Focused feedback assertions: 2 passed in 12.33 seconds.
- Session-performance reconciliation, next-Strategy access, and adaptive Memory: 3 passed in
  29.85 seconds.
- All daily durable recovery crash boundaries with session performance: 7 passed in 79.96 seconds.
- Real-data peer-momentum enhanced-index scenario: 1 passed in 12.06 seconds.
- Checkpoint round-trip plus peer-momentum regression after making session performance optional:
  2 passed in 32.03 seconds.
- Full pytest: 115 passed in 281.38 seconds.
- Ruff over src and tests: all checks passed.
- Public imports for QlibxProject, DailyExecutionFlow, and SessionPerformanceEvidence: passed.
- uv build: qlibx 0.1.0 sdist and wheel built successfully after the sandbox-blocked PyPI lookup was
  rerun through the approved network boundary.
- Git diff check: passed.

## Remaining limitations

The feedback entry limit defaults to 256 and currently fails rather than paginating. A Strategy sees
only the latest completed session-performance record, not an arbitrary historical range. A zero
opening NAV produces undefined ratio fields. External cash flows, subscriptions, dividends,
settlement, and funding need separate attribution policies before return calculations can support
them.

The peer-momentum acceptance is a bounded two-stock K200 peer group with KODEX 200 residual. It
proves the engine capability shape, not scientific equivalence to the historical strategy and not
coverage of all 18 alpha calculations. Real-short execution, partial-fill lifecycle, OMS
reconciliation, and intraday behavior remain outside current product scope.