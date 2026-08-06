# 004 Exact-cost batch exchange

## Why

Execution must distinguish product, side, effective time, liquidity, lot, cash, and holdings without
silent fallback. A scalar mutable exchange would also discard per-name clipping evidence and make
the 3,000-name acceptance path an afterthought.

## Outcome

qlibx now has concrete Stock, ETF, Index, and Factor boundary models; only Stock and ETF compile to
the current executable set. KrxExchange resolves exact effective-dated cost rules, preflights the
entire order batch, and returns immutable Fill and FillDiagnostic rows. Cash clipping and final Fill
use one cost calculator. The matcher preserves input order and returns candidate ending state
without mutating an Account or caller holdings.

## Responsibility and flow

Instrument and cost schedule models validate once at registration. compile creates dataclass hot
path terms. match_batch resolves every instrument, quote, and exact rule before calculation; any
unsupported selector returns no Fill. Supported orders apply volume, holdings, last-sell lot, cash,
minimum-cost, and zero-value rules in deterministic order.

## Alternatives and trade-offs

The clipping sequence and last-sell exception are derived from Microsoft Qlib
qlib/backtest/exchange.py in vendored snapshot main@79633dd under MIT. qlibx does not copy mutable
Order or Account coupling. It adds batch preflight, exact product policies, immutable DTOs, and
structured diagnostics. Floating-point Money remains a current limitation pending a precision
contract; fixture values are deterministic and explicit.

## Validation

- Full pytest with task basetemp: 41 passed.
- Ruff and git diff check: passed.
- uv build: built qlibx-0.1.0 sdist and wheel.
- Fixtures cover UC-COST-001 through UC-COST-004, last-sell lot behavior, volume diagnostics, and
  stable 3,000-name batch output.

## Remaining limitations

The result is a pure execution candidate. No Account commit, mark, feedback, event callback,
checkpoint, intraday order lifecycle, or OMS reconciliation exists yet. Current impact behavior is
the documented quadratic participation formula and needs additional parity fixtures before a
nonzero default can be claimed.
