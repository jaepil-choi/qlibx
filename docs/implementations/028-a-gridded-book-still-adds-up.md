# 028 — A gridded book still adds up

## Why this exists

`rescale` returns exact ratios. A caller who needs weights **on a grid** had to quantize the
returned mapping afterwards — and quantizing re-breaks the total `rescale` had just matched.

```python
w = rescale(raw, long=Decimal("1"), short=Decimal("0"))     # sums to exactly 1
w = {k: v.quantize(QUANTUM) for k, v in w.items()}          # now sums to 0.99…
```

So every caller wanting both properties wrote the same repair: settle a second time, by hand, onto
some chosen name. A testbed strategy did exactly that, which is how the gap surfaced. The framework
already owned both halves — `_settle` in `weighting.py`, `QUANTUM` in `optimize.py` — and simply
never joined them.

## The decision that shaped it

**Order is the whole content of the fix: quantize first, settle second.** The reverse order is the
bug. Settling makes the side reach its target; quantizing afterwards moves every member off that
total again. Doing it the other way round, the residual is computed *from already-gridded members*,
so placing it lands the side exactly on target with every weight still on the grid.

That ordering only holds inside `_settle`, where both steps are visible. It cannot be reconstructed
by a caller holding the finished result, because by then the information about how much each member
moved is gone.

```python
rescale(weights, *, long, short, grid=None) -> Weights
```

`grid=None` keeps today's behaviour exactly: exact ratios, one settle, nothing rounded. The
parameter is opt-in because a book feeding further arithmetic wants the unrounded ratio, and
rounding it by default would be the package quietly deciding a precision the caller did not ask for.

## Two refusals the grid makes necessary

**A budget that is not itself on the grid.** Weights on a `0.01` grid cannot sum to `1.005`. Without
this check the residual would silently land off-grid on one member, which is precisely the property
the argument was added to guarantee — so it is refused with the target named.

**A grid finer than `QUANTUM`.** Architecture 5.3 makes `1E-12` the canonical grid every
package-produced weight lands on. `optimize` already refuses inputs finer than it; `rescale` now
refuses the same way, and for the same reason: coarser is a caller's choice, finer is a claim the
package does not honour downstream.

Quantization uses `ROUND_HALF_EVEN` explicitly rather than the ambient decimal context, so the
result stays context-independent like the rest of the module.

## Trade-offs

- **The residual still concentrates on one member.** On a coarse grid it is more visible than in
  exact arithmetic: three equal names on `0.01` give `0.33 / 0.33 / 0.34`. The distortion goes to
  the largest member, where it is smallest in relative terms, ties broken by instrument name so the
  result is order independent. A caller who finds `0.34` unacceptable wants a finer grid, not a
  different placement rule.
- **`weighting.py` now imports `QUANTUM` from `optimize.py`.** Both are pure sibling modules in
  `portfolio/`, so there is no cycle and no I/O reaching in — but the canonical grid is now stated
  in one place and consumed in two, rather than being redefined.
- **A member can quantize to zero on a coarse grid.** It stays in the book at zero rather than
  being dropped, consistent with `signal_weight` keeping zero-signal names visible.

## Validation

```
uv run pytest -q                  577 passed (from 567)
uv run ruff check src/ tests/     clean
```

Ten focused tests in `tests/portfolio/test_weighting.py`. The load-bearing one is
`test_quantizing_after_rescale_is_what_the_grid_argument_replaces`: it reproduces the caller-side
bug — sum falling to `0.99` after quantizing — and then shows the same call with `grid=` holding
both properties at once. The rest pin the settled residual (`0.33/0.33/0.34`), order independence,
`grid=None` being unchanged, and the four refusals.
