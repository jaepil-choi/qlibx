# Committed real-market test fixture

This directory holds a **minimal excerpt of real KRX market data** so that the test suite runs
against genuine prices, sessions and tradability everywhere, not only on machines that carry the
local `data/DW` warehouse.

## Contents

| File | Rows | Meaning |
|---|---|---|
| `observation_price_daily.parquet` | 88 | `available_at`, `instrument`, `close`, `volume`, `is_supervised` at the venue close |
| `execution_krx_daily.parquet` | 88 | `trade_at`, `instrument`, `is_tradable`, `close` at the venue close |
| `benchmark_weight_daily.parquet` | 88 | `available_at`, `instrument`, `benchmark_weight` as a dated index weight panel |
| `fixture.json` | — | exact provenance: spec, universe, session counts, flag counts, weight unit/scale/quantum/tolerance |

Scope: 4 KOSPI 200 constituents, 22 real trading sessions, 2026-04-01 to 2026-04-30.

`is_supervised` is published as **observable data**, not as a venue rule: whether to hold a
supervised name is the Strategy's economic judgement. Trading halts are the opposite — they are a
venue fact and appear as `is_tradable` on the execution input.

## Benchmark weights are a proper subset, deliberately

The benchmark panel carries the vendor's index weights for these four constituents only, so its
per-date sum is roughly `0.549`, not `1`. That is not a defect to normalise away: a weight-sum
invariant over an allocation input is **coverage-scoped**, and the uncovered remainder flows to
cash. A fixture that summed to one would have hidden this.

Weights are stored as fractions at a single declared scale (`weight_scale`), converted once from
the vendor's percent notation. The extractor refuses rather than rounds when a value would need
more precision than that scale. `weight_quantum` records the coarsest step the vendor actually
resolves in this slice, and `weight_tolerance` is derived from it as `coverage x quantum` rather
than pinned to a constant, so regenerating over a finer-published window tightens the tolerance
instead of leaving a stale allowance.

## Provenance and regeneration

Produced verbatim by:

```powershell
uv run python scripts/extract_dw_fixture.py --out tests/fixtures/real \
  --asof 20260331 --start 20260401 --end 20260430 --universe-size 4
```

The upstream warehouse under `data/DW` is local vendor data and is **not** redistributed. This
excerpt exists solely to make the package's own tests reproducible; it is a de-minimis sample of
closing prices and session flags, not a dataset product, and it must not be treated as a
redistribution of the vendor feed.

`tests/acceptance/test_real_warehouse.py` runs against this committed excerpt unconditionally. When
the full warehouse is present it additionally regenerates the same slice and asserts the committed
rows still match the warehouse, so silent drift fails the suite.
