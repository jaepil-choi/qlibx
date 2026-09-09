# 075 -- a signed book split as the signal says cannot use `Rebalance.of`, and the direct build must be assembled from three docstrings

**Status:** **CLOSED 2026-09-04 by record `154`** (one-shape campaign Step 3). `Rebalance.signed(
weights, *, gross=1)` builds the market-neutral residual book from signed weights, splitting
long/short exactly as the signal produced them (`gross=2` is the textbook $1/$1 book `of` cannot
reach). `of` now calls `portfolio.weighting.rescale` instead of carrying a second copy of it, which
made its gross exposure exact — the old book-wide settle let a short side's crumb land on a long
name. `Budget`'s docstring names both budgets as numbers, `Rebalance`'s lists the three ways in,
and `SKILL.md` carries `signed`. Found 2026-09-04 by the scenario testbed run 4
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-002**, with the cause half of **F-010**),
against `vqapr-0.4.0`. Confirmed against source 2026-09-04. This is the gap `071`'s last bullet
names in passing ("that gap is the reason the author met this refusal at all"), filed on its own
because it is an authoring-surface issue and `071` is a message issue. `018` (closed, record
`090`) documented that `Rebalance.of` tops out at half a textbook book; this is the next step: the
author who takes the documented escape hatch is left without a rail.

**Touches:** `src/vqapr/authoring.py:566-609` (`Rebalance.of` docstring: "Build the `Rebalance`
directly to go past it", no example); `:647-655` (the comment inside `of` that knows the exact
`1.000000000001` failure and settles it on the book); `:557-563` (`Rebalance` has a one-line
docstring and no constructor guidance); `src/vqapr/portfolio/budgets.py:26-36` (`Budget` names
five fields and gives no valid values); `src/vqapr/portfolio/weighting.py:161-196` (`rescale`, the
only place that says quantise first and settle second, and the only one that names `QUANTUM`).

## What happens

The specification was ordinary for a market-neutral residual strategy: signed weights over stocks
and factor legs whose absolute values sum to one, the long/short split being whatever the signal
produces, cash the net residual. `Rebalance.of` cannot say it -- it splits `invested` evenly and
its docstring says so plainly -- and points at the direct constructor.

The direct constructor is `Rebalance(target_weights=, cash_weight=, budget=)`. To fill it the
author had to learn, from three different places:

1. what a valid `Budget` is -- its docstring names five fields and no values; the only numbers on
   the surface are one sentence inside `Rebalance.of`'s docstring ("the signed budget admits
   positions in `[-1, 1]` and cash in `[-1, 2]`");
2. that the sum must land on one *exactly* and a one-ulp miss is refused -- also in `of`'s
   docstring;
3. that a two-sided book has to be quantised onto `QUANTUM` **and then** settled, in that order --
   only in `rescale`'s docstring, which the author found by reading `help()` on every name the
   `of` docstring mentioned.

They assembled it, quantised each weight, and 307 sessions later a seventeen-name all-short book
left a gross of `1.000000000001` and a cash of `2.000000000001` against `cash_upper = 2`. The
refusal (`071`) named neither number. The fix was to settle the residual onto the largest weight
-- exactly what `Rebalance.of` does for its own callers at `authoring.py:647-655`, in a comment
that describes this precise failure ("the leftover -1e-12 pushes cash to 1.000000000001, one
crumb ABOVE the fully-uninvested bound") and settles it on the book. The direct path leaves that to
the author and does not say so.

## Why

`Rebalance.of` was built to keep authors off the arithmetic, and its bound-and-even-split was a
deliberate ceiling (`018`). The direct constructor was left as the escape, but it is a bare
dataclass with a validator: it checks the last digit and explains nothing. The knowledge needed to
use it correctly exists in the package -- in `of`'s own implementation and in `rescale` -- and is
not reachable from the constructor an author is told to use.

## What to do

- Give the signed case a constructor. `Rebalance.signed(weights, *, gross=1)` -- signed weights in,
  normalised to the gross, quantised and settled on the book, budget derived -- is the case a
  market-neutral strategy actually has, and it makes the residual impossible to leave behind. An
  `invested_split=` on `of` is the smaller alternative but still forces the author to state a
  split the signal already chose.
- Failing that, a worked example of the direct build beside the sentence that recommends it: the
  `Budget` for a signed book, `rescale(..., grid=QUANTUM)` in front of it, and one line saying why
  the settle comes after the quantise.
- `Budget`'s docstring should show the two budgets `of` derives (long-only and signed) as values,
  so an author who must write one has something to copy.
- `Rebalance`'s own docstring should say that weights are validated to the last digit and point
  at `rescale` and `QUANTUM`; today it is one line.

Related: `071` (the refusal), `018` (the ceiling), `014` (a shipped cap that disagreed with itself
about a short; the budget bounds for a signed book were last written down there).
