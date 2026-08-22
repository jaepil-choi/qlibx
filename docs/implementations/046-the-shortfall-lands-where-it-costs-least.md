# 046 — The shortfall lands where it costs least, and a batch says who paid what

Two gaps closed together because both are the same omission: the split between instrument
categories was implemented in the *charge* and never reached the *decisions and evidence* around
it.

## 1. Buys were funded in ticker order

Canon 6.3 and its own checklist (line 4125) are explicit:

> 각 side 안에서는 **delta 내림차순**, 동률은 `instrument_id` 사전순

The implementation iterated `sorted(instruments)` — pure alphabetical order. Records 043–045
replaced the affordability *search* with a solve but never touched the *order* it was applied in.

Measured, two names at the same price, NAV 1,000,000 with a 3bp commission:

```text
targets   A000001 = 10% (10 shares)      Z999999 = 90% (90 shares)
before    A000001 -> 10                  Z999999 -> 89     <- the big line is clipped
after     A000001 ->  9                  Z999999 -> 90
```

Canon states the reason and it is economic, not aesthetic: *"실패했을 때 잃는 것은 delta로 잰다."*
A name already at 9.9% of a 10% target loses 0.1% if refused; a name at 0% of a 2% target loses the
whole 2%. Funding the largest delta first leaves the shortfall on the position that misses by
least.

Ordering alphabetically instead makes the loser depend on **ticker spelling**. An ETF sleeve listed
as `A069500` sorts behind most of a KRX universe, so the sleeve was clipped for that reason alone —
directly against the enhanced-index work these categories exist for.

`_buy_order` now sorts by `-notional, instrument_id`. **Delta is compared in money, not share
count**: one share of a 900,000 KRW name and one of a 9,000 KRW name are not the same intent, and
cash is what is being rationed. Sells are unaffected — they release cash regardless of the order
they are counted in, so only the buy pass has an order that changes the result.

## 2. A batch could not say what each category paid

`FillBatch` exposed `total_commission` and `total_tax` and nothing else. Separating the rates
(records 035–038) is only half the job: the number that justifies an ETF sleeve is **what the
sleeve cost**, and a batch reporting one total cannot produce it.

`Fill` now carries `kind`, and `FillBatch.cost_by_kind()` aggregates by it:

```text
etf                  commission 1800.0000  tax 0
stock                commission 1800.0000  tax 12000.000
batch total          commission 3600.0000  tax 12000.000
```

**The category is stamped on the fill rather than looked up afterwards.** A fill is evidence: it
records what the venue actually charged it as, so a roster edited later cannot change what a past
fill says it paid. It is also what lets a consumer holding no `ExchangeRulesView` — a run record, a
report — separate the sleeve from the direct book. A venue declaring no categories collects under
`None` rather than being dropped or guessed.

## Trade-offs

**`Fill` now duplicates a fact the venue also knows.** That is deliberate: the duplicate is a
*record of what happened*, not a second source of truth for what the rules are. The alternative —
a helper taking a rules view — would give a later roster edit the power to rewrite past evidence.

**`_buy_order` calls `rules.notional` once per candidate to sort.** That is one extra pass over the
buy side per rebalance; measured against the 0.034s a 3,000-name plan already takes (record 041),
it does not register.

## Validation

- `uv run pytest -q` — **655 passed**; `uv run ruff check src tests` clean.
- **All three guards discriminate.** Reverting the buy order to alphabetical fails both ordering
  tests; removing `kind` from the KRX fill fails the category-cost test. Restored, all pass.
- The category split is proved to reconcile: `sum(cost_by_kind().values())` equals
  `total_commission` and `total_tax`, so the breakdown is not a second set of books.
- Ordering is proved on money, not shares: a 3-share 900,000 line is funded ahead of a 100-share
  100,000 line even though it sorts last alphabetically and asks for fewer shares.
