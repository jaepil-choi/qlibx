# 012 — Absorb the grid residual at the cash edges

## Why this exists

`optimize()` refused problems it had already proved feasible.

The entry feasibility check establishes that the exact optimum satisfies `cash_range`. The solve
then quantizes every free weight onto the canonical grid, and cash takes the residual. When the
exact answer sits **on** a cash bound, that residual can push cash a few multiples of `1e-12` past
it, and the final range check refused.

The boundary review found this while pinning an unrelated property: a fifteen-shape sweep solved
fourteen, and the fifteenth turned out not to be infeasible at all. Its exact optimum reaches the
budget precisely at `lam = 23/60`; four repeating thirds each round up at twelve decimals, the total
overshoots by `1e-12`, and cash lands just under its floor.

A caller passing the natural `cash_range=(0, 1)` hits this whenever the exact answer is `cash = 0` —
which is every fully-invested book. The refusal was our grid making a solvable problem look
infeasible, not the caller posing an unsolvable one.

## What changed

`src/vqapr/portfolio/optimize.py` gains `_absorb_grid_residual`. When cash falls outside its
declared range by no more than the quantization budget, the shortfall is moved between cash and one
free weight, and cash lands exactly on the bound it missed.

Three properties are preserved rather than traded away:

- **The box still holds.** The residual is placed on an **interior** weight only — never one already
  resting on a bound — so a name clipped to its cap stays exactly at its cap. `binding_lower` and
  `binding_upper` therefore stay accurate.
- **The budget identity stays exact.** The same amount leaves one side and arrives at the other, so
  `sum(w) + cash == 1` holds bit for bit, in the caller's own decimal context.
- **Permutation invariance survives.** Selection walks instruments in sorted order, like the solve
  it corrects.

If the shortfall exceeds the budget, or no interior weight has the slack, the refusal stands. This
absorbs rounding residue, never a genuine infeasibility.

## Trade-offs

**Repair over refusal, because the infeasibility is ours.** The alternative was to keep refusing and
tell callers to inset `cash_range` themselves. That pushes a numeric artifact of this function into
every caller's arithmetic, and gets it wrong the first time someone writes the obvious `(0, 1)`.

**Interior-only placement over nearest-weight placement.** Nearest would be simpler and would
sometimes push a capped name `1e-12` past its cap — a box violation, which is exactly what the
acceptance criteria assert cannot happen.

**No widening of the accepted range.** Cash is snapped onto the bound rather than accepted just
outside it. `Budget.validates_cash` downstream is an exact inclusive comparison with no tolerance,
so a result accepted just outside here would be refused a moment later at intent construction.

## Also in this change

- `AllocationInvariants`' tolerance is now pinned at its declared edge: exactly at
  `weight_sum_upper + tolerance` is accepted, one quantum past it is refused, and a zero tolerance
  admits nothing above the declared sum. The committed fixture sums near `0.549` against a ceiling
  of `1.0004`, so nothing in the real data ever approached the edge and the allowance could have
  been any value at all while every other assertion still passed.
- The same allowance is now pinned **on the path a run actually takes**: a benchmark inflated past
  the ceiling is driven through a real point-in-time window and `SingleNameCap.project()` itself
  refuses. The helper being correct does not prove the shipped constraint consults it.

## Validation

- `uv run pytest -q` — 298 passed (from 292).
- `uv run ruff check` and `ruff format --check` — clean. Package imports.
- `uv run python showcases/show_005_enhanced_index/run.py` — the full two-run spine still executes,
  21 rebalances, 67 whole-share fills, monitoring raising 10 cap-drift findings, and the fill
  journal replay matching the committed Account exactly.
- The fifteen-shape sweep now solves fifteen of fifteen, with the count pinned so a regression that
  refuses any of them fails.
