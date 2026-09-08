# The price columns, and what the data cannot tell you about them

## Contents

- Why the ordering proves the shape but not the roles
- Naming a fill price is a declaration, not an inference
- When the source has returns and no prices
- The warning only you can give

## Why the ordering proves the shape but not the roles

The profiler reports inequalities that hold on every row. Four numbers where two bound the other
two is the shape of a price bar, and that much the data does prove:

```
always: low <= open      always: open <= high
always: low <= close     always: close <= high
```

What it does not prove is **which of the two inner numbers is the open**. Swap them and every one
of those inequalities still holds, on every row, forever. There is no query that separates them.

So the ordering goes in the "proven" column and the assignment goes in the "ask" column, and the
question to the user is specific: *these two columns are both bounded by the other two; which one
is the session's first trade?*

## Naming a fill price is a declaration, not an inference

Which observation is used as the execution price is an explicit declaration. vqapr does not choose
one for the user and does not fall back to another when the declared one is missing or invalid — it
fails instead.

**A column's name is not that declaration.** That a column looks like an opening price is not a
statement that it should be traded at.

## When the source has returns and no prices

Every execution path in vqapr is quantity × price. There is no return-native fill path, and none
is coming — a portfolio return claimed without a price axis is a forbidden shortcut, not a missing
feature.

If the source gives period returns only, register a dataset of derived unit prices:

```
P_0 = b > 0
P_t = P_{t-1} * (1 + r_t)
```

Three things about this:

- **It is not a package operation.** You perform the conversion; the result registers like any
  other dataset, under the same contract.
- **The base `b` is the user's choice** and you explain what it does — it sets the scale at which
  lot rounding and per-share costs bite, so it is not cosmetic.
- **The values are a derived unit NAV, not an observed market price.** Say so, and keep saying so:
  a backtest over them cannot claim realistic execution, and that belongs in the result's
  limitations.

## The warning only you can give

vqapr knows the fill *time*; it does not know when the fill *price* was observed, because that is
not in the data. So a configuration that fills at the session close using the opening price passes
every check the package can make.

When you see that pairing, say plainly that the price could not have been traded at that time, and
offer the alternative. The output of this warning is **a limitation on the result, not a new
validation** — widening the package's judgment here would create a guarantee that is only half
true, and a half guarantee invites more trust than none.

## Related

- [point-in-time.md](point-in-time.md) — the same distinction for the availability column
- [universe-and-tradability.md](universe-and-tradability.md) — whether the name could be traded
  at all
