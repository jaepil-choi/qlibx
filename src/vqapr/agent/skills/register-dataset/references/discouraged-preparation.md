# Calculations that do not belong in the source

Moving averages, cumulative sums, ranks and time-axis aggregations all make **one row's value
depend on another row's observation**. Done while preparing the source, that dependency becomes
invisible: the registered table holds a number, and nothing about it says which observations went
into it or when they were available.

## vqapr does not forbid this, and could not

The user can precompute anything in their own pipeline before vqapr ever sees the file. Blocking
one route while the other stays open is not blocking — and worse, a rule that looks like a guard
invites the trust a real guard would earn. So this is a **skill guideline, not a package rule**,
and if the user proceeds anyway, that choice lands in the result's limitations.

## What to look for in a registration definition

- **a moving average or rolling statistic** — the row's value spans a window; does that window end
  at or before the row's `available_at`, or does it straddle it?
- **a cumulative sum or running total** — same question, with an unbounded window
- **a cross-sectional rank or z-score** — needs every name's value at that instant; if some names
  publish later, the rank as of the earliest name's availability is not the rank anyone could have
  computed
- **a resampling or period aggregation** — a monthly value stamped at the month start is a
  look-ahead of up to a month
- **a fill-forward** — carries a value into instants where nothing was observed, which is a claim
  about persistence and not a fact
- **a "latest available" join** — silently becomes a look-ahead when the right-hand table is
  restated

## Say what would have to be true

The useful form of this warning is not "do not do that". It is: *this pattern is safe only if X,
and here is how to check X.*

For a 20-day moving average on daily closes: safe if the window ends at the row's own session and
the closes are stamped at their own session's close. Then say what to run to confirm it.

## The alternative

Express it as a DataModel. It computes a new dataset from the registered ones, under the same
point-in-time boundary every other read obeys, and it is a reviewable component with declared
inputs and a recorded lineage — rather than a step in a script nobody reads again.

The `make-datamodel` skill covers writing one.

## Related

- [point-in-time.md](point-in-time.md) — the availability question each of these patterns bends
- [grain-and-cost.md](grain-and-cost.md) — registering the vendor's grain as well, so the
  collapsing stays visible
