# 022 Current-price rebalance sizing

## Why

Daily order conversion divided current-session execution prices into `AccountSnapshot.nav`, whose
held positions were still valued at the previous session's mark because EXECUTION precedes MARK at
the same close timestamp. Every rebalance after the first could therefore under- or over-size the
new target and misclassify the resulting cash clip as liquidity behavior.

## Outcome

Before converting target weights to quantities, the execution callback now computes a liquidation
value from actual cash plus every held quantity valued at the same validated execution-price cross
section used for the orders. It rejects non-finite or non-positive sizing capital. Execution
evidence records both `sizing_nav` and `sizing_price_role`, keeping the calculation distinct from
the historical `account_before.nav` snapshot.

## Responsibility and flow

Account remains the authority for cash and quantities; the flow does not commit a synthetic mark
before trading. ExecutionView remains the authority for callback-time prices. The conversion is a
pure calculation over those two explicit inputs, after coverage for every target and held
instrument has succeeded. Exchange still owns lot, cash, cost, and holding clipping.

## Alternatives and trade-offs

Moving MARK before EXECUTION was rejected because it would add an Account commit solely to prepare
an order calculation, change feedback/version semantics, and couple the execution convention to a
valuation event. Documenting prior-mark sizing as a limitation was rejected because the selected
daily profile claims target-weight conversion at the execution callback and the stale basis caused
observable drift.

Using execution prices means sizing assumes every held name can be valued at the same cross-section
as the candidate orders. This is appropriate for the current full-fill close-price profile; a
different executor must declare and evidence its own sizing convention.

## Validation

- Daily execution acceptance: `uv run pytest tests/acceptance/test_execution_scenarios.py -p no:cacheprovider --basetemp=<task path> -q`
  -> 8 passed.
- Full suite: `uv run pytest -p no:cacheprovider --basetemp=<task path> -q` -> 86 passed.
- Ruff on `src/qlibx/flow/daily.py` and the execution acceptance test -> passed.
- `git diff --check` -> passed.

The real-DW two-rebalance regression switches from A000660 to A005930. It verifies the current
price sizing NAV of KRW 10,051,100, a 131-share target, and only the expected one-share lot
residual; the old path used KRW 9,970,800 and bought 130 shares.

## Remaining limitations

The pre-execution Account snapshot still cannot state when its stored marks were observed. This
change avoids using those marks for sizing; mark freshness and STALE valuation evidence are handled
as a separate Account-contract change.
