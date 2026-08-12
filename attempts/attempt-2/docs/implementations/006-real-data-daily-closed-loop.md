# 006 Real-data daily closed loop

## Intent

Implement the first usable callback-driven simulation loop for UC-CLOSED-LOOP-001 and
UC-EXEC-002. A decision must remain immutable until a later execution callback, only a committed
FillBatch may change actual state, every held instrument must be marked, and the next Strategy
callback must consume committed cash, NAV, positions, and feedback rather than its requested
target.

## Data audit

The repository DW CSV was compared directly with both downstream Parquet layers before selecting
an execution input.

- data/DW/fng_stock_daily_prices.csv: 8,709,828 rows, 5,670 tickers, no duplicate
  ticker/trade-date keys.
- data/preprocessed/adjusted_prices.parquet: 8,651,872 rows, 4,962 tickers, no keys absent from
  DW. The omitted population is 57,951 J-prefix rows and five A165270 rows.
- The preprocessed cumulative adjustment multiplier equals the reverse product of later DW
  adjustment factors for all 8,651,872 included rows. Adjusted OHLC is raw OHLC divided by that
  multiplier; return is exactly raw close/base minus one. Volume, transaction amount, market cap,
  trading-halt, and admin-issue mappings reconcile.
- A065180 has 82 rows whose cumulative multiplier is zero, producing non-finite adjusted prices.
- data/qlibx/daily_market.parquet is an exact 8,651,872-row projection of the preprocessed fields,
  including those 82 non-finite rows. Its available_at is exactly date minus one day on every row.
  That rule is not supported by the DW trade-date meaning and is unsafe for close-price execution
  or close-return PIT decisions.

The acceptance therefore reads unchanged raw KRW close, volume, and return inputs from the DW CSV.
It uses a bounded two-ticker/four-session projection and adds only the Architecture-declared
15:30 Asia/Seoul close availability. Back-adjusted prices are not used as physical Fill prices.

## Implementation

- Dataset registration can optionally bind an observation/event-time field. Scoped views preserve
  it and support an exact session query while still applying the mandatory availability cutoff.
- StrategyView can expose a Flow-supplied immutable AccountSnapshot through a protocol boundary.
  Actual cash, NAV, holdings, version, and feedback cursor become portable state-access lineage.
- StrategyDraft distinguishes target, explicit hold, and research-only actions.
- DailyExecutionFlow registers deterministic DECISION, EXECUTION, MARK, and MONITOR callbacks.
  Decision publishes an immutable target intent without mutation. The next-session-close callback
  queries its own ExecutionView, converts target weights from the current actual AccountSnapshot,
  calls the pure Exchange matcher, and lets Flow commit one atomic FillBatch.
- MARK commits all held close prices before MONITOR reads the snapshot. Monitoring publishes only
  evidence and verifies that the Account version does not change.
- Account checkpoints preserve positions, cash, version, journal, and applied event identities.
  Restoring a checkpoint preserves CAS and duplicate-event authority.

## Trade-offs and limitations

The first profile is deliberately optimistic: one close price is used for the whole batch, intraday
path and impact are unmodelled, and partial fills occur only if an Exchange participation policy is
configured. Signed Strategy weights fail before execution because physical construction belongs to
the later portfolio slice. The flow is single-use and local; child execution branches are the next
milestone.

The real-data acceptance depends on the repository-local DW file and is not an installed-package
fixture. This is intentional evidence for the current workspace, while installed-package tests
remain independent of private data.

## Validation

- Actual DW values: A005930 wins the 2024-01-02 cross-section, then fills 129 shares at the real
  2024-01-03 close of KRW 77,000. Cost is KRW 14,899.5; committed cash is KRW 52,100.5 and marked
  NAV is KRW 9,985,100.5.
- The 2024-01-04 decision reads Account version 2 and feedback cursor 2, sees the committed 129
  shares, and emits an explicit hold.
- One-pass and checkpoint/resume executions finish with identical Account snapshots.
- uv run pytest with isolated basetemp: 48 passed.
- ruff check src tests: passed.
- uv build: built qlibx 0.1.0 sdist and wheel.
- Installed-environment import smoke for qlibx and DailyExecutionFlow: passed.
