# show_004 — One real signal, two execution profiles

The same frozen strategy, the same real KRX closes and the same agendas, executed twice. The runs
differ **only** by the registered Exchange component, so the difference in outcome is exactly the
declared venue friction.

## Profiles compared

| | Academic | KRX |
|---|---|---|
| Quantity | fractional | whole shares, rounded toward zero |
| Commission | none | 3bp, both sides |
| Sale tax | none | 20bp, sells only |
| Short positions | permitted by the listing | refused by the profile |
| Fill | full at the selected close | full at the selected close |

## Observed on real data

2026-04-01 to 2026-05-29, 6 KOSPI 200 constituents, 34 rebalances, 1,000,000,000 KRW initial cash.

| Metric | Academic | KRX |
|---|---|---|
| final NAV | 1,895,960,196.32 | 1,865,987,436.94 |
| dealt fills | 80 | 77 |
| traded notional | 20,871,637,793.57 | 20,699,378,200.00 |
| commission | 0 | 6,209,813.46 |
| sale tax | 0 | 19,763,149.60 |
| total cost | 0 | 25,972,963.06 |
| whole shares only | no | yes |

Effective KRX cost is **12.55bp of traded notional**: 3bp commission on both sides plus 20bp sale
tax charged on the sell half. The NAV gap of 29,972,759 is larger than the charged cost because
whole-share rounding also leaves each rebalance slightly under its intended weight.

Both runs independently replay cash and positions from their own fill journal and assert an exact
match with the committed Account. A mismatch aborts the showcase.

## What this does not claim

Neither profile models price ticks, daily price limits, auction microstructure, queue position,
partial fills from liquidity, borrow and locate for short sales, or margin. The KRX profile claims
only the rules listed above.

A fully invested weight book is deliberately avoided: the strategy targets 98% invested and holds a
2% cash buffer. At exact `cash_target = 0` a fractional weight book can round a hair over NAV at
Decimal precision and be refused before mutation, which is correct fail-closed behaviour rather
than something to paper over.

## Reproduce

```powershell
uv run python showcases/show_004_krx_execution_profile/run.py
```

Inspect `outputs/report.html`, `outputs/trace.json` and `outputs/inputs/fixture.json`.

Requires the local warehouse at `data/DW`. Environment: repository `uv` environment, Python 3.12+,
DuckDB 1.5+.
