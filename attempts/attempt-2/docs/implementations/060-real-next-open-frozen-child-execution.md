# Real next-open frozen-child execution

## Intent

Close `GAP-EXECUTION-CONVENTION-001` for public daily full-batch simulation by comparing the same
immutable `decision_intent:v1` under next-session-close and next-session-open execution without
rerunning Strategy or Model code.

## Observable outcome

A caller can select exact parent decision artifact IDs with `FrozenDailyExecutionSpec` and invoke
`QlibxProject.execute_frozen_daily()`. Package-owned close/open profiles execute at distinct explicit
event calendars, read only price observations available at those instants, and publish isolated
child Account, Fill, profile/convention, dataset, state, and parent lineage. The parent artifact and
its producer remain unchanged.

## Responsibilities and flow

`DailySimulationSpec` and `DailyRunRequest` retain `session_closes` as the mark/monitor cadence and
add an optional `session_opens` calendar. `DailyExecutionProfile.execution_timing` selects either
`NextSessionCloseExecutor` or `NextSessionOpenExecutor`; `execution_price_role` remains an independent
semantic binding, so schedule and price selection are separate without a speculative class
hierarchy. The default close timing and empty open schedule are omitted from compatibility JSON,
preserving existing config, request, profile, and recovery identities.

The project facade loads every exact `decision_intent:v1` artifact, creates a new Exchange and
Account from the frozen child spec, and delegates to the existing `execute_frozen()` flow. Existing
`ExecutionEvidence` already carries event time, profile/convention, price role, fills, Account
before/after, limitations, and dependency edges. Existing recovery points already carry exact
pending execution timestamps, so no evidence or recovery schema revision was needed.

Real-DW and bundled sample registrations use long-form open and close event rows. Each row has its
own `event_time == available_at`; a close-available price is therefore invisible at the earlier open
event even though both roles share one immutable dataset registration.

## Alternatives and trade-offs

Overloading `DailySimulationSpec.decision_times` with parent artifact IDs was rejected because it
would mix Strategy invocation and frozen execution responsibilities. A distinct
`FrozenDailyExecutionSpec` keeps exact parent selection and child authority explicit. Replacing
`session_closes` with a generic calendar was rejected because it would break the established
mark/monitor and recovery contract. A public `FillConvention` class hierarchy was deferred: two
current schedule planners plus an independent semantic price role provide the required axes, while
a protocol becomes useful only when a third reference-price behavior such as VWAP has shared logic.

Using one daily row whose availability is close for both open and close was rejected as look-ahead
unsafe. Silently falling back from missing/future-hidden open price to close was also rejected; the
flow returns typed pre-mutation failures instead.

## Compatibility and limitations

Existing next-close specs remain the default, and their frozen config, request, and profile hashes
are unchanged. The change is additive and does not alter `decision_intent:v1`,
`execution_result:v1`, simulation checkpoint, or recovery schemas. Current support assumes one
open or close reference price for the whole cross-sectional batch. Intraday VWAP/order-book paths,
market impact, generic partial-fill work, executable short, and production OMS remain out of scope.

## Validation

The pre-change daily/recovery/public-contract baseline passed 46 tests in 56.12 seconds. The final
focused public-contract, real-DW close/open, failure, recovery, installed sample, architecture, and
scenario suite passed 64 tests in 69.95 seconds; focused Ruff passed. The installed sample preserved
one parent content hash and one producer call, produced open `120`/83 shares and close `125`/80
shares on isolated Accounts, and rejected the close-available price at the open event with
`EXECUTION_SESSION_PRICE_MISSING` and no execution artifact.

The complete source suite passed 266 tests in 135.83 seconds. `uv run ruff check .`, curated public
imports for `FrozenDailyExecutionSpec`, `QlibxProject`, and `NextSessionOpenExecutor`, and
`git diff --check` passed.

`uv build` produced `qlibx-0.1.0-py3-none-any.whl` and `qlibx-0.1.0.tar.gz`; archive inspection
confirmed the execution-convention sample runner/manifest and updated bundled qlibx skill/recovery
guide in both artifacts. A fresh Python 3.12.13 environment installed the wheel, imported qlibx from
that environment's `site-packages`, materialized a fresh project, and ran the sample. The installed
result preserved the parent hash and producer call count, used the same exact parent dependency for
both children, produced close `125`/80 shares and open `120`/83 shares on distinct Accounts, and
rejected a close-available price at the open event with no execution artifact.
