# Move cadence into Strategy session callbacks

## Why this change exists

The initial runtime calendar slice implemented the then-documented design: a frozen
`SessionCalendar`, calendar derivation rules, and a preconstructed `Timeline`. A later end-to-end
review exposed a responsibility contradiction. The architecture said Flow only delivered events
and owned no economic rules, while `SessionCalendar × TriggerPolicy` made Flow choose every
Strategy decision before the run. That also made `LastSessionOfMonth` possible only because Flow
could inspect future sessions that Strategy itself could not observe.

This contradicted the product's path-dependent Model-state contract. `EveryNSessions` should advance
from Strategy memory as current sessions arrive, including sessions that produce no decision and
across explicitly chained daily runs.

## Outcome

The canonical PRD and companion architecture now specify:

- the separately prepared execution table is the authoritative executable-session source;
- no separate calendar parquet, calendar provider, open/close table, or calendar derivation path is
  required by the current daily product;
- Flow delivers each current execution session in deterministic order and does not interpret
  Strategy cadence;
- `StrategyModel.on_session()` owns stateful trigger, warm-up, cooldown, and decision logic and
  returns either `NoDecision` or a `PortfolioIntent`-shaped value;
- a successful `NoDecision` callback commits Model progression state, while an exception or invalid
  result restores the previous memory and creates no committed state; and
- `LastSessionOfMonth` is not a current capability because current-session Strategy code cannot know
  whether another session remains in the month. `UC-CALENDAR-001` is retired without reusing its ID.

The production foundation now provides execution-parquet session extraction, `SessionEvent`, a
daily `SessionStream`, Strategy callback and `NoDecision` contracts, strict detached JSON memory,
content-addressed local committed state, and a minimal session-first `SimulationFlow` that proves
the callback/state boundary. The former calendar, derivation, Timeline, trigger, and calendar test
helper modules were removed.

## Responsibility and flow

```text
separately prepared execution parquet
  -> data.scan distinct physical trade_at values
  -> Flow builds one current SessionEvent at Strategy.callback_time()
  -> StrategyModel.on_session(current context only)
       -> NoDecision       -> validate -> commit Model state -> next session
       -> PortfolioIntent  -> validate -> commit Model state -> later execution spine

callback exception / invalid result
  -> restore pre-callback memory
  -> no Model-state commit
```

Strategy context deliberately has no calendar, future-session list, execution table, Exchange, or
mutable Account. The Flow can hold the frozen input needed to deliver the next callback without
making that future input accessible to Strategy.

## Alternatives and trade-offs

- **Keep SessionCalendar only as a convenience** was rejected because it preserves two competing
  session authorities and invites future-aware trigger evaluation back into Flow.
- **Keep `LastSessionOfMonth` but hide the calendar from Strategy** was rejected because Flow would
  still execute the Strategy's economic rule on its behalf.
- **Split `should_decide()` and `decide()`** was rejected because the first call can advance a
  counter before the second fails, and retry can then double-advance state. One callback gives one
  validation and commit boundary.
- **Share one trigger vocabulary with DataModel** was rejected because DataModel materialization
  evaluation times and Strategy decision cadence are different operations. Materialization now
  takes explicit frozen evaluation times.
- **Treat observation price rows as execution sessions directly** was rejected. Observation and
  execution remain separately prepared parquet files with different schemas and consumers even
  when they originate from the same daily OHLCV.
- **Implement the complete PortfolioIntent/execution engine in this slice** was deferred. The
  callback boundary uses the documented PortfolioIntent structural surface, while target economics,
  order planning, fills, and Account mutation remain their later vertical slices.

## Evidence and validation

Tests were replaced before implementation. The new focused suite initially failed during collection
because the approved `ExecutionTableSpec` and state-store surfaces did not yet exist.

```text
uv run python -m pytest tests -q -p no:cacheprovider
before source changes -> 94 passed in 1.70s

uv run python -m pytest \
  tests/runtime/test_session_stream.py tests/flow/test_session_callbacks.py \
  -q -p no:cacheprovider
before implementation -> 2 collection errors on the expected empty modules
after implementation -> 7 passed in 7.86s

uv run python -m pytest \
  tests/runtime tests/flow tests/boundaries/test_runtime.py \
  -q -p no:cacheprovider
-> 16 passed in 0.65s

uv run python -m pytest tests -q -p no:cacheprovider
-> 94 passed in 1.45s

uv run ruff check .
-> All checks passed

uv run ruff format --check src tests
-> 144 files already formatted

uv run python -c "import vqapr; ..."
-> vqapr ExecutionTableSpec SimulationFlow SessionStream

uv build
-> built dist/vqapr-0.1.0.tar.gz and dist/vqapr-0.1.0-py3-none-any.whl

git diff --check
-> passed; Git emitted only the checkout's LF-to-CRLF warnings

rg legacy runtime symbols in src/tests
-> 0 matches
```

The old suite had 13 standalone-calendar/Timeline tests. They were replaced by 13 physical-scan,
execution-session, callback, strict-memory, and state-atomicity tests, so the final total remains the
94-test baseline count; unrelated tests were not removed.

The ordinary final-validation process launch first failed with the managed-Windows
`CreateProcessAsUserW failed: 5` error. The repository environment detector reported an ASCII user
profile, and the same commands completed through the scoped escalated PowerShell boundary. One
Ruff-format-only finding in `models/memory.py` was applied mechanically before the clean rerun.

## Remaining limitations and follow-up

- `SessionStream` intentionally supports one execution instant per local daily session. Intraday
  multiple execution instants remain future scope.
- The minimal Flow stops after validating and committing a Strategy callback. Order planning,
  Exchange execution, Account commit, valuation, and feedback are still empty later slices.
- `PortfolioIntent` is currently a runtime-checkable structural contract, not the eventual validated
  concrete construction model. The later portfolio slice must implement its budget, target, bound,
  lineage, and account-version validation before execution is enabled.
- The in-memory Model state store covers strict JSON memory only. Durable payload storage and
  working checkpoints remain later state-store work.
- The current content digest identifies memory bytes only. Compatibility binding to Model
  implementation/configuration and payload identity must be added with the durable state store.
- The execution-table session reader validates session-source schema and timezone. Full
  `is_tradable => selected price > 0`, exact cost/listing coverage, and batch snapshot validation
  remain Exchange/preflight work.
