# Tolerance is the framework's, and your comparison is strict

## Why there is a tolerance at all

A book executes in **whole lots** and is marked **after** its fills. So a realised weight lands a
little off the target even when nothing went wrong — a 20% cap on a name whose lot size does not
divide evenly into 20% of NAV cannot land on exactly 20%.

Without a tolerance, every such run reports breaches, and a report where everything breaches tells
the reader nothing.

## Write the strict comparison

In `observe`, compare exactly. Do not add your own epsilon, do not round, do not "allow a bit".

The framework judges each finding's `excess` against:

```
max(bound × 1%, 10bp of NAV)
```

once, in one place, and files the finding as one of three:

| verdict | meaning |
|---|---|
| `held` | inside the bound |
| `within_tolerance` | outside, by less than the line above |
| `breached` | outside by more |

**Only `breached` makes the contract `ok: false`**, and the counts of all three are reported so
nothing is hidden by the classification.

## Why one place

If each rule applied its own tolerance, two rules on the same book would disagree about
what "close enough" means, and a report combining them would be comparing different rulers. Judging
in one place is what makes the three counts addable.

It also means a reader can find the line. An epsilon buried in a user's `observe` is invisible in
the record; the framework's line is stated with every finding as `tolerance`.

## Overriding it

A `tolerance` property on your rule returning a `Decimal` share of NAV replaces the
framework's line for that rule. `None` — the default — keeps it.

Override when the mandate itself states a tolerance. Do not override to make a breach go away: the
`within_tolerance` count exists precisely so a nearly-breaching book is visible rather than
laundered into `held`.

When you do override, say so when reporting — the number is in the record, but a reader comparing
two rules will assume the same ruler unless told.

## Reporting these three

Never collapse them. *"No breaches"* is a different statement from *"no findings outside the
bound"*, and a book that spent a year at `within_tolerance` is a book that was at its limit the
whole time.

`compliance.rules` in a `StrategyReport` keeps the split, with the worst excess and when it
happened, and the offending names by count.
