# show_009 — the same strategy, before and after the authoring contract

One cross-sectional momentum view, expressed twice: once as a hand-assembled portfolio the way a
user had to write it before Step 7, and once as `Rebalance.of(long=...)`. Both produce **the same
book**, which is the whole point — the ceremony was never carrying information. It was carrying the
risk of getting arithmetic wrong.

Reproduce:

```
uv run python showcases/show_009_authoring_contract/run.py
```

## What it shows

**Identical output, four fewer lines of arithmetic.** The hand-written form normalises, scales by
the invested fraction, quantises onto the canonical grid, and then has to notice that three names
rarely divide evenly — so cash absorbs a residual rather than being the `1 - invested` the author
was picturing. `sum(weights) + cash` is checked *exactly*, so a residual of one ulp is refused by
the same invariant that catches a real mistake.

**The signed book is where hand-arithmetic reliably breaks.** For a long/short book, `invested` is
*gross* exposure while `sum(weights)` is *net*. The showcase prints both numbers:

```
gross : 0.800000000000   (the invested fraction, put fully to work)
cash  : 1.000000000000   (1 - invested would have said 0.2)
```

An author computing `cash = 1 - invested` is wrong for every signed book, and wrong by the entire
portfolio for a dollar-neutral one — which is fully invested and nets to zero. That mistake was in
the package's own first implementation of `Rebalance.of` and was caught by running the awkward
cases rather than reasoning about them.

**The budget is derived, not declared.** `LONG_ONLY` when nothing is shorted, `SIGNED` when
something is. An author who declares it separately can contradict their own weights; an author who
never states it cannot.
