# 158 — a residue within tolerance is not a breach: judged once, reported in three

**Closes:** `docs/issues/archive/086`. **Branch:** `fix/086-tolerance-and-three-buckets`, off `develop`
after record `157`. **Campaign:** none — the contract block in `flow/records.py` is one-shape
campaign Step 6 territory, and this lands first as a small addition so Step 6 reshapes the split
rather than the fold. **Authority:** the owner, 2026-09-05.

## Why this exists

`optimize` places weights on the grid; the book then executes in whole lots and is marked after
its fills, so the realised weight lands a little off the target. `single_name_cap.monitor`
compared strictly (`size > ceiling`) and `ConstraintFinding` had no tolerance, so in the run that
filed the issue **40 of 82 rebalances were recorded as violations of a cap the optimiser had
respected**, worst excess 0.01%p, in the same `held/checked` counter as the one real breach —
4.89%p of intra-month drift. The record read `held 42/82, ok: false` and its `fix` said to loosen
the bound, which would have loosened a real cap for a rounding residue.

The owner's ruling, and the arithmetic that made it easy: the two populations were **489x apart**
(1bp against 489bp), so a generous line separates them with room on both sides and needs no
precision. `max(bound × 1%, 10bp of NAV)`: ten times the residue on a 10% cap, one forty-ninth
of the breach. Declined: an absolute money default (vqapr has no currency; money is a unit-less
`Decimal`), a per-lot derived resolution (right, but `ConstraintCall` deliberately cannot see the
venue), and a tolerance on `ConstraintBounds` (the one place it could leak into `project` and
widen the feasible set).

## What changed

**`constraints/findings.py`.** `default_tolerance(bound)` and the two constants.
`StampedConstraintFinding` — the framework's stamp on an author's finding — gains
`tolerance` (given, or the default from the finding's own bound) and two properties: `verdict`
(`held` when the author passed it; `within_tolerance` when the author failed it and `excess`
is inside the line; `breached` beyond) and `breached`. The author's `passed`, `measured`,
`bound`, `excess` are untouched.

**`constraints/evaluation.py`.** `evaluate_constraints` stamps each finding with the author's
override, read once from `Constraint.tolerance` and refused when it is not a finite non-negative
`Decimal` — a typo must not silently become the default.

**`authoring.py::Constraint.tolerance`.** A property returning `None` by default, documented as
the one lever: override with a `Decimal` share of NAV.

**`flow/records.py::contract_report`.** Each constraint reports `held`, `within_tolerance`,
`breached`, `checked`, `tolerance` (the widest used), `worst_within`, `worst_breached`; `ok` is
`breached == 0 and checked > 0`; `cause` names the breach count, the tolerance and the worst
excess; `fix` names the three remedies including the constraint's own `tolerance`.

**`flow/valuation.py` + `flow/context.py`.** The `vqapr.monitoring` row carries `verdict` and
`tolerance` beside `passed`, so the table compliance questions are asked of can split the
populations the way the record does.

**`SKILL.md`.** The monitoring-table bullet and the Constraint paragraph: compare strictly, the
framework applies the tolerance, three verdicts, `tolerance` property to override.

## What did not change

`single_name_cap.py`, `no_short`, and the constraint scaffold: **zero lines.** Every constraint,
shipped or authored, keeps comparing strictly; the judgment moved to the one place that sees all
of them. `SingleNameCap`'s existing `tolerance` argument is the benchmark's sum-to-one invariant
and is unrelated. `project` and the optimiser's feasible set are untouched by construction.

## Validation

- `uv run ruff check src/` — clean.
- New: `tests/constraints/test_a_residue_within_tolerance_is_not_a_breach.py` — the default's
  numbers, the reporter's two populations getting two verdicts, the override in both directions
  and its refusal, and the contract block splitting 41/40/1 with `ok: false` on the one.
- `uv run pytest tests/ -q -m ""` — **1460 passed** in 800s (fast + the thirteen slow journeys + the eight showcase gates); no flake this run.
