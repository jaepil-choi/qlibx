# show_005 — enhanced index over a published alpha

An alpha run publishes its allocation as an ordinary dataset; a second run subscribes to that
dataset **and** to the committed benchmark panel and builds a benchmark-relative enhanced index on
the KRX execution profile. Both halves are real runs on the public spine.

Reproduce:

```
uv run python showcases/show_005_enhanced_index/run.py
```

It reads `tests/fixtures/real`, so it runs on a clean checkout with no vendor warehouse.

## What this demonstrates

| Claim | How it is shown |
|---|---|
| Publication is a dataset, not a new subsystem | The alpha run's callback evidence goes straight to `publish_run_allocation`, which shares the staging, atomic-exposure and registration body with `materialize` |
| A run subscribes to two allocation inputs | `EnhancedIndex.requirements()` declares `benchmark_weight_daily` and the published `alpha_allocation` as ordinary `DataRequirement`s; both arrive through the same point-in-time window, so the combination happens on the subscription path |
| The stamp is derived, so the chain is honest | The alpha's `available_at` comes from its own reads; the index callback runs at 09:00, after the 08:30 alpha decision it consumes |
| Long-only is emergent | The alpha is signed and dollar-neutral. Nothing strips the short leg; the registered `no_short` intersected with `single_name_cap` does |
| The bounds are the shipped constraint set's own | `optimize` is called with `context.constraint_bounds` — what the registered `NoShort` and `SingleNameCap` projected for that occurrence — not with a local copy of the same rule |
| Frozen names survive exactly, or the freeze is refused | Each callback pins the holding with the least slack against its own upper bound. 10 callbacks got that holding back verbatim; on 10 others overnight drift had pushed it past its cap, and `optimize`'s own refusal is what released the freeze |
| The constraint set is enforced, and monitored separately | 21 completed rebalances are 21 intents that passed their projected bounds — a failing intended finding stops the run. The marked account is then read back at every monitoring occurrence, and its findings are reported rather than assumed |
| The account is verified against its own journal | Cash and every position are rebuilt from the committed fill journal and compared to the committed `AccountSnapshot`; a mismatch aborts the run |
| Output is deterministic | The whole pipeline runs twice into separate projects, and both the reported outcome and the SHA-256 artifact digests must match |

## What this does NOT demonstrate

- **No cost model beyond the declared KRX profile.** 3bp commission both sides and 20bp sale tax on
  sells, whole shares, long only. No ticks, price limits, queue position, liquidity or borrow.
- **`active_norm` is the L2 norm of active weights**, not a realised or forecast tracking error. It
  is recorded after the decision and never re-enters the construction.
- **No ex-ante tracking-error constraint.** A portfolio quadratic has no representation in
  per-instrument bounds, so it is monitoring only.
- **Four names are not an index.** The benchmark is a four-constituent slice of a two-hundred-name
  index, so its weights sum to roughly `0.56`, not `1`. The uncovered remainder is cash.
- **The alpha is a demonstration signal**, a demeaned cross-sectional cheapness tilt scaled to a 4%
  gross active budget. It exists to be signed and dollar-neutral, not to be profitable.

## An unpredictable halt does not stop a rebalance

Tradability is an **execution-time** fact. At 08:30 the Strategy cannot know whether a name will be
halted at 15:30, so it never freezes for it — it keeps targeting the weight it wants, every session.

This run halts one name for six sessions and asserts the whole loop:

- the Strategy kept ordering that name throughout, because it had no way to know,
- the venue refused **exactly six** fills with `ZeroDealtReason.NONTRADABLE`,
- the position simply stayed put and the rest of the book traded normally,
- monitoring kept reporting the resulting breach against the committed account,
- and the next session tried again.

If a position is already over its cap when the halt lifts, the next rebalance resolves it. While the
halt lasts, there is nothing to do and nothing pretends otherwise. A holding you cannot trade is a
market fact, not a compliance failure — `optimize` reports it in `frozen_outside_box` rather than
refusing, and monitoring judges the account separately.

## Results

Last verified 2026-08-18 against `vqapr-0.1.0+show-005-working-tree`, on the committed April 2026
KRX slice (22 sessions, 21 callbacks, 4 instruments).

| Metric | Value |
|---|---|
| alpha occurrences published | 21 |
| allocation inputs subscribed | `alpha_allocation` + `benchmark_weight_daily` |
| shipped constraints registered | `no_short`, `single_name_cap` (cap 0.10 above index weight) |
| rebalances | 21 |
| freezes returned verbatim | 10 |
| freezes released as out of box | 10 |
| monitored occurrences | 21 |
| marked short positions | 0 |
| cap-drift findings between rebalances | 10 (worst excess 0.0078 over a 0.3212 ceiling) |
| dealt fills | 67 (whole shares) |
| commission / sale tax | 227,197.80 / 276,818.20 |
| replayed cash == committed cash | 518,988,184.00 |
| final NAV | 1,168,772,684.00 (from 1,000,000,000) |
| final active-weight L2 norm | 0.0118 |

The NAV gain is what the committed April 2026 slice did: `A000660` closed +44.0% and `A005930`
+16.3% over the window. Roughly 56% of the book is invested, so most of the move is the index slice
itself, not the tilt.

## Reading the numbers honestly

`current` is quantized onto the canonical grid before `optimize` is called, which is what a caller
must do: a raw NAV-derived ratio carries far more digits than the grid and the bound-exponent guard
refuses it. The refusal itself is proved in `tests/portfolio/test_optimize.py`, not here.

The subscribed alpha is validated at consumption time as a signed allocation summing to zero within
a declared neutrality tolerance. No constraint owns that input, so the consuming Strategy checks it
before a single weight moves.

**The cap-drift findings are the honest result, not a defect.** `single_name_cap` is defined
relative to the index, and the index moves. The book is built at 09:00 against the previous
session's weight and marked at 16:30 against the current one, so a position sized exactly to
yesterday's ceiling sits above today's. On 2026-04-02 the marked weight is `0.32670`, which is
yesterday's ceiling `0.32680` less whole-share rounding, against today's `0.32300`. A
benchmark-relative cap is held at each decision, not continuously between them, and this showcase
reports that rather than smoothing it away. `no_short` has no moving reference, so a marked short
position would mean the long-only account authority failed — that one aborts the run, and it never
fired.

`outputs/` is gitignored, and each replicate builds its own project under it.
