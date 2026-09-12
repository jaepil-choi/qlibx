# 154 — a signed book splits as the signal says: `Rebalance.signed`, and `of` via `rescale`

**Closes:** `docs/issues/archive/075`. **Branch:** `step-03-075-signed-book`, off `develop @ fd5b169c`.
**Campaign:** `docs/refactoring/2026-09-04-the-one-shape-campaign.md`, Step 3. **Authority:** the
owner, 2026-09-04.

## Why this exists

The scenario testbed's run 4 had an ordinary specification for a market-neutral residual arm:
signed weights whose absolute values sum to one, the long/short split being whatever the signal
produced, cash the net residual. `Rebalance.of` cannot say it and says so — it takes two mappings
and splits `invested` **evenly** between them, which is why `018` recorded that it tops out at
half a textbook $1-long/$1-short book. Its docstring points at the direct constructor, and the
author who took that documented escape hatch was then left assembling three docstrings: what a
valid `Budget` is (its own docstring named five fields and no values), where the canonical grid
lives, and that quantising has to be settled afterwards or the sum-to-one invariant refuses at the
twelfth digit.

The second half is that `of` contained a **second copy** of `portfolio/weighting.py::rescale` —
quantise onto the grid, then settle the residual — with one difference that turned out to be a
defect rather than a variation.

## What changed

- **`Rebalance.signed(weights, *, gross=1)`** (`authoring.py`). Signed weights in, the sign
  carrying the side; `gross` is the sum of absolute weights; the long and short targets are taken
  in the ratio the signal produced and handed to `rescale`. `gross=2` is the textbook $1/$1 book.
  Cash is the net residual. The budget is `SIGNED` with cash in `[-1, 2]` and targets in
  `[-1, 1]`.
- **`Rebalance.of` calls `rescale(..., grid=QUANTUM)`** instead of quantising and settling itself,
  and `per_side` is quantised because it becomes a side target and `rescale` refuses a target that
  is not itself on the grid.
- **`Budget`'s docstring names the two budgets as numbers**, in code, plus why `cash_upper` is 2
  on a signed book.
- **`Rebalance`'s class docstring** lists the three ways in and states that weights are validated
  to the last digit, pointing at `rescale` and `QUANTUM` for anyone building one directly.
- **`SKILL.md`** gets the `signed` paragraph and a one-line example beside the `of` one.

`authoring` now imports `portfolio.weighting`, which imports only `portfolio.optimize`. No cycle.
`signed` is a classmethod on an already-exported class, so `public.__all__` is unchanged.

## The measured difference, which is the point of the step

The campaign warned that `of` settles the rounding residual on the **book's** largest |weight|
while `rescale` settles **per side**, and that outputs could move. They move, in exactly two of
nine probed cases, and the move is a fix:

```
of(long={"A": 1}, short={"B": 1, "C": 1, "D": 1})
  before   A=0.500000000001  B=C=D=-0.166666666667
  after    A=0.500000000000  B=C=-0.166666666667  D=-0.166666666666
```

Three shorts at -0.5/3 do not divide evenly. The old book-wide settle placed that residual on the
largest position by absolute size — **the long** — so the short side's crumb landed on a long
name, the long side missed the target it was given, and the book's gross came out at
1.000000000002 for an `invested` of 1. `invested` is documented as gross exposure. Each side now
lands exactly on its own target, so gross is exact.

**Cash did not change in any probed case**, including the neutral books the old comment was
written to protect: the residual still never reaches cash, it is just settled per side on the way.

Two smaller behaviour changes, both from "no silent fallback":

- `of` with an `invested` below one grid step used to return a book of **all zeros with cash 1** —
  a decision that says nothing. It now refuses and says the grid is the reason.
- `signed` refuses a side whose target would quantise to zero, rather than silently returning a
  long-only book from a mapping that declared shorts.

## Decisions

- **Opposite sign conventions between the two constructors, deliberately.** `of` refuses a
  negative weight because the side is chosen by which mapping a name appears in; in `signed` the
  sign IS the side. Two constructors taking different inputs can afford different conventions.
  What they must not do is accept the same input and mean different things by it.
- **`signed` is `SIGNED` even when the mapping holds no shorts.** A budget that flipped to
  `LONG_ONLY` on a day the signal found no shorts would refuse the book on the first day it did.
- **A zero weight is kept as a flat position.** Dropping it would make the returned book disagree
  with the mapping the author passed, which is the silent kind of behaviour this campaign is
  removing.
- **`gross` is not bounded at 1.** Leverage is a real declaration, and what actually constrains
  the book is the per-position bound of `[-1, 1]` — which is why a 130/30 expressed over two names
  is correctly refused while the same book over several names is not.

## Validation

- `tests/models/test_a_signed_book_splits_as_the_signal_says.py`, 17 tests. `signed`: seven longs
  against eleven shorts gives 0.388888888889 / -0.611111111111 rather than a 50/50 book;
  `gross=2` reaches the textbook book; cash is the net residual across three books with the same
  gross; the budget stays SIGNED with no shorts; a zero weight survives; four refusals name the
  value and the rule. `of`: the measured regression is pinned by value, and gross equals
  `invested` exactly over four unevenly-dividing books.
- `tests/extension/test_authoring_contract.py` (which asserts the sum-to-one and in-budget
  properties over unevenly-dividing books) unchanged and green; `tests/portfolio/`,
  `tests/models/`, `tests/boundaries/`, `tests/qa/`, `tests/constraints/` green.
- `ruff check src/` clean; `vulture` at its two-item baseline. Full fast suite: see the merge
  commit.
