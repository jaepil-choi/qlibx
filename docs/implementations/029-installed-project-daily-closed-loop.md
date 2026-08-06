# 029 Installed-project daily closed loop

## Why

The current daily engine already provided point-in-time reads, next-session-close execution,
authoritative Account and Strategy Memory commits, session performance, portable evidence, and
durable recovery. A package user could not reach that capability through the project facade,
however. `QlibxProject.invoke` stopped at research, while executable acceptance assembled
`DailyExecutionFlow`, `Account`, `KrxExchange`, and `BacktestClock` through repository test helpers.
That left the PRD public-workflow promise proven internally but not usable from an installed
project.

## Observable outcome

A user can now pass a Strategy callback and one typed `DailySimulationSpec` to
`QlibxProject.run_daily`. The facade runs the supported next-session-close loop, and a second
Strategy decision can consume the first committed Fill/Mark feedback, Strategy Memory, and latest
completed session performance. Repeated frozen input is deterministic, resume does not duplicate
commits, and changed Strategy or economic configuration requires an explicit branch.

The separately materialized `daily-closed-loop-v1` sample uses only documented public imports. It
selects A005930 on 2024-01-02 and A000660 on 2024-01-04 from eight unchanged bounded DW rows,
executes both decisions at the next session close, and finishes with 72 A000660 shares after exact
cost, cash, holding, and lot handling. The existing basic research sample and CLI default remain
unchanged.

## Responsibilities and flow

- `DailyAccountSeed`, `DailyMarketBinding`, and `DailySimulationSpec` own the portable public input.
  Cross-field validation requires unique stock/ETF instruments, one exchange, one Account currency,
  no participation, zero impact, and a sorted timezone-aware schedule.
- The caller supplies a Strategy callback and its explicit fingerprint. The spec derives a stable
  configuration fingerprint from the Strategy fingerprint, Account seed, instruments, exchange,
  and market binding. Run identity and schedule remain in the existing request fingerprint.
- `QlibxProject.run_daily` constructs the isolated Account, compiled Exchange, canonical daily
  profile, Clock, request, and existing `DailyExecutionFlow`. Flow remains the only owner of event
  ordering, Account/Memory commits, publication, failure evidence, and recovery.
- The public facade exposes only the current full-fill, instant-settlement daily profile. Cash,
  holding, and lot clipping remain explicit. Participation, impact, intraday, pending/cancel, and
  OMS behavior fail at typed configuration rather than becoming misleading public options.
- `SampleMaterializer` now selects an exact bundled sample ID. The old basic ID remains the default;
  the daily sample uses a distinct source directory and destination, preserving preview,
  idempotency, and modified-file conflict protection.

## Alternatives and trade-offs

Accepting preconstructed Account, Exchange, Clock, and Flow objects was rejected because it would
preserve the assembly burden that this change is intended to remove. A declarative Strategy loader
and run CLI were deferred because they require a separate source-loading and configuration-schema
contract; Strategy callback/IoC remains the public extension seam.

Exposing the existing participation and impact fields was rejected. Participation currently models
only event-local clipping without pending-order lifecycle, and the daily flow does not provide the
total-market-volume input required by non-zero impact. Publishing those options would overstate
current support. The facade therefore chooses a deliberately optimistic but truthful full-fill
profile and preserves its limitations in evidence.

The new daily sample was added beside the existing basic sample rather than replacing it. This adds
one explicit sample ID to the public materialization method but avoids changing files already copied
into user projects.

## Validation

- `uv run --cache-dir .uv-cache pytest tests/test_public_daily.py -q --basetemp C:\tmp\qlibx-public-daily-m3c -p no:cacheprovider` -> 7 passed.
- `uv run --cache-dir .uv-cache pytest tests/test_public_daily_sample.py -q --basetemp C:\tmp\qlibx-public-daily-sample-final -p no:cacheprovider` -> 3 passed.
- `uv run --cache-dir .uv-cache pytest -q --basetemp C:\tmp\qlibx-m11-full-20260807 -p no:cacheprovider` -> 125 passed in 135.19s.
- `uv run --cache-dir .uv-cache ruff check .` -> all checks passed.
- Public import smoke for `DailyAccountSeed`, `DailyMarketBinding`, `DailySimulationSpec`, and
  `QlibxProject` -> passed.
- `git diff --check` -> passed.
- `uv build --cache-dir .uv-cache` -> built qlibx 0.1.0 sdist and wheel after the sandbox-blocked
  isolated build dependency lookup was rerun through the approved network boundary.
- Wheel inspection -> 94 entries; `qlibx/simulation.py` and all six daily sample files are present.
- Installed-wheel smoke from an isolated target -> imported qlibx from the wheel target, selected
  A005930 then A000660, completed two executions, and finished with 72 A000660 shares.

## Remaining limitations

This public path does not load Strategy code from YAML or expose a run CLI. Strategy fingerprint
selection remains caller-owned. It supports only a fresh cash Account with stock/ETF instruments;
initial positions need a separate typed seed contract if required. It does not model volume
participation, market impact, intraday prices, pending/cancel orders, partial-fill lifecycle, actual
settlement, lifecycle cash flows, real short, OMS reconciliation, or production authority.

The sample proves installed-package capability shape and committed feedback, not scientific alpha
quality, execution realism, or capacity. A future volume/impact milestone must define distinct
PIT-safe available-volume and total-market-volume roles before expanding this facade.