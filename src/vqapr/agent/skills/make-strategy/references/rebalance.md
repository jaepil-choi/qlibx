# `Rebalance.of` and `Rebalance.signed`

Two constructors, two conventions for a short, and one of them cannot express a book the other
can. Choosing wrong produces a book that runs, reports, and is not the one the signal asked for.

## `of` — relative conviction, sides declared by mapping

```python
vq.Rebalance.of(long={"A": 2, "B": 1}, invested="0.9")
```

- The numbers are **relative conviction**: A is liked twice as much as B. Normalising, rounding
  onto the canonical grid and balancing against cash is the package's arithmetic.
- A short is declared by **which mapping** the name appears in: `short={"A": 2}` means twice as
  short. Never a negative number here.
- Passing both sides makes the book signed automatically.

### The limit that decides the choice

**`of` splits `invested` evenly between the two sides.** So it tops out at half a textbook
$1-long / $1-short book, and it **cannot say "more shorts than longs"**.

If the split is a property of the signal rather than a constant you chose, `of` will quietly
override it.

## `signed` — the signal decides the split

```python
vq.Rebalance.signed({"A": 0.8, "B": 0.2, "C": -1.0})   # 0.5 long, 0.5 short
vq.Rebalance.signed(weights, gross=2)                  # the textbook $1/$1 book
```

- Weights are **signed**: a negative number *is* the short.
- `gross` is the sum of absolute weights. `gross=2` is $1 long and $1 short.
- The long/short ratio comes out **exactly as the signal produced it**.

## Cash

The net residual, either way. A dollar-neutral book therefore has cash 1 — that is not a bug and
not idle capital to reinvest.

## Which to use

| the split between long and short is… | use |
|---|---|
| a constant you chose, and even | `of` |
| whatever the signal produced | `signed` |
| long-only | either; `of` reads more clearly |

## Declining

```python
return vq.Hold(reason="no name scored above zero")
```

Prose a human reads. Spaces are fine; only an empty string is refused. Warm-up callbacks — the
ones before the lookback has filled — are `Hold`, not failures.

## What is not yours to do

- **Do not make weights sum to one.** Hand-normalising and then handing the result to `of` applies
  the arithmetic twice.
- **Do not top up an under-allocated result.** See
  [composition-and-budget.md](composition-and-budget.md).
- **Do not express a short as a negative number in `of`**, or as a `short=` mapping in `signed`.
  Each constructor refuses the other's convention, but the refusal is easier to avoid than to read.
