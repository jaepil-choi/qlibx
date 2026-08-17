# Committed real-market test fixture

This directory holds a **minimal excerpt of real KRX market data** so that the test suite runs
against genuine prices, sessions and tradability everywhere, not only on machines that carry the
local `data/DW` warehouse.

## Contents

| File | Rows | Meaning |
|---|---|---|
| `observation_price_daily.parquet` | 88 | `available_at`, `instrument`, `close`, `volume`, `is_supervised` at the venue close |
| `execution_krx_daily.parquet` | 88 | `trade_at`, `instrument`, `is_tradable`, `close` at the venue close |
| `fixture.json` | — | exact provenance: spec, universe, session counts, flag counts |

Scope: 4 KOSPI 200 constituents, 22 real trading sessions, 2026-04-01 to 2026-04-30.

`is_supervised` is published as **observable data**, not as a venue rule: whether to hold a
supervised name is the Strategy's economic judgement. Trading halts are the opposite — they are a
venue fact and appear as `is_tradable` on the execution input.

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
