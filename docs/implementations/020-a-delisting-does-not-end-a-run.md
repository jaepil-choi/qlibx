# 020 — A delisting is a market fact, not a batch failure

## Why this exists

Two places refused a run when a held instrument had no row in the execution table:

```python
# flow/simulation.py
if selected.missing_held_instruments:
    raise ValueError("missing selected execution value for held instruments: …")

# orders/planning.py
if missing_held:
    raise ValueError(f"missing selected execution price for held instruments: {missing_held}")
```

Canon 6.1 had already assigned that case elsewhere. One snapshot query splits three ways:

| 상황 | 판정 |
|---|---|
| 조회 결과에 행이 없다 | **zero-dealt + reason** — 상장 전/상폐 후. 시장 사실 |
| `is_tradable = false` | **zero-dealt + reason** — 거래 불가. 시장 사실 |
| `is_tradable = true` 인데 가격이 없다 | **batch 실패** — 데이터 계약 위반 |

and warned exactly what conflating them costs:

> 3,000종목 × 250세션에서 정지와 상폐는 매일 나온다. 묶으면 run이 첫 주에 죽는다.

`AcademicExchange.execute` already implemented the split correctly, publishing `ABSENT`. The raise
in the Flow ran first and never let it.

The failure was found the way canon predicted. A KOSPI 200 reproduction stopped at `A003410`,
which left the index on 2024-06-12 and delisted on 2024-07-08 — an ordinary event that ended the
run outright.

## What changed

- The snapshot no longer refuses a held instrument absent from the table. The Exchange sees the
  absence and reports it as typed `ABSENT` evidence, which is what that reason exists for.
- NAV values what can be priced at this instant. An unpriceable holding contributes nothing to
  the denominator rather than being priced from a stale quote — every later weight is converted
  against that number, so an invented one would spread silently.
- `plan_orders` keeps such a holding at its current quantity and asks for no trade. A position
  that cannot be priced cannot be sold, and closing it at an invented price would fabricate the
  proceeds.
- `OrderRequest` widens accordingly: an unresolved request may still be *requested* — that is how
  a target for an unlisted name reaches the venue — but it may not settle an existing holding.

## Trade-offs

**A delisted position stays in the book at its last mark, forever.** That is the honest outcome:
the money is genuinely tied up in something that cannot be sold, and every later allocation works
around it. Record 019 makes the staleness visible by recording when each mark was observed, so
reporting can measure it afterwards.

**A run no longer fails loudly on missing execution data.** The typed zero-dealt evidence is the
signal instead, which is quieter. That is the intended trade: the alternative ends a
3,000-name run in its first week over an event that happens constantly.

## Validation

- `uv run pytest -q` — 515 passed, with the acceptance test that asserted the old refusal
  rewritten to assert the position survives and the run continues.
- `show_005_enhanced_index` and `show_008_alpha_family_ensemble` regenerate byte-identical
  manifests: the change only reaches paths that previously ended the run.
- In the reproduction, `A003410` now trades through the seventeen sessions between leaving the
  index and delisting, and is carried at its last price thereafter.
