# 034 Filter sessions in the caller-declared calendar

## Intent

Session callers computed a KRX trading date in `Asia/Seoul`, while `ObservationStore` compared that
date to UTC-normalized timestamps. An observation just after KST midnight therefore belonged to the
next KRX session but the prior UTC calendar day and silently disappeared. Existing fixtures did not
cross that boundary.

## Observable outcome

Every session read now declares the calendar timezone that gives `session_date` its meaning. The
store converts the observation instant to that timezone before comparing the local date. A boundary
fixture proves that the same two observations select different rows under KST and UTC calendars.

Signal analysis freezes `return_session_timezone` beside its date. Daily execution uses the same
`DailyExecutionProfile.session_timezone` both to derive the date and to query prices and volumes.

## Responsibilities and flow

- `StrategyView.session` requires a keyword-only `session_timezone` and carries it through the
  private read boundary.
- `ObservationStore.query` rejects a session date without a timezone and filters after `tz_convert`.
- `SignalAnalysisRequest` validates its IANA return timezone; `AnalysisFlow` passes it to the view.
- Daily flow, bundled strategies and acceptance strategies explicitly declare `Asia/Seoul`.
- PRD `GAP-TIME-001` ties the source-timezone and session-calendar rules to regression fixtures;
  Architecture §17 records the single declared-time design.

## Alternatives and trade-offs

A default of UTC was rejected because it would preserve the bug for user strategies. Converting the
requested date to a precomputed UTC interval was not needed for the small session frames and would
require additional DST-boundary reasoning; pandas timezone conversion directly expresses local
calendar membership.

The public API break is deliberate at version 0.1.0. A missing declaration fails immediately rather
than selecting a plausible but economically wrong session.

## Validation

```
.venv/Scripts/python.exe -m pytest tests/test_session_timezone.py tests/acceptance/test_analysis_scenarios.py tests/test_public_daily.py tests/test_public_daily_sample.py tests/test_sample.py -q -p no:cacheprovider --basetemp=.agent/runs/pytest-c3-targeted-019fd96d
-> 17 passed in 52.64s

.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp=.agent/runs/pytest-c3-full-019fd96d
-> 150 passed in 394.14s

.venv/Scripts/python.exe -m ruff check .
-> All checks passed!

git diff --check
-> clean
```

## Remaining limitations

- `session_timezone` changes the source-compatible API for custom strategies and direct view users;
  there is no silent compatibility default.
- The basic bundled strategy bytes changed. A previously materialized user copy is intentionally
  reported as `ChangeAction.CONFLICT` on apply rather than overwritten.
- The package validates timezone identity and filtering, not whether a user-selected timezone is the
  economically correct exchange calendar.