# 086 — a constraint has no tolerance, so quantisation residue is counted as a violation and the fix says loosen the bound

**Status:** **OPEN -- owner ruling 2026-09-05: a generous tolerance, judged in one place,
with the record split in three.**

- **Default `tolerance = max(bound * 1%, 10bp of NAV)`**, and the author may override it. On a 10%
  cap that is 0.1%p: ten times the worst residue this file measured (0.01%p = 1bp) and one
  forty-ninth of the real breach in the same run (4.89%p = 489bp). The two populations are 489x
  apart, so a generous line separates them with room on both sides -- which is why the owner chose
  generosity over precision here.
- **An absolute money default is declined.** vqapr has no currency concept; money is a unit-less
  `Decimal`, so `10000` means one thing to a KRW book and another to a USD one. Expressed as a
  share of NAV the default needs no currency at all.
- **A per-lot derived resolution is declined**, though it is the arithmetically right number:
  `ConstraintCall` deliberately cannot see the venue (least authority), and wiring `quantity_step`
  into the constraint layer to get it would invert that design for a threshold that does not need
  to be exact.
- **Where it lives: neither candidate in the section below.** Not on the author's
  `ConstraintFinding` and not on `ConstraintBounds`, but in `constraints/evaluation.py`, once, for
  every constraint. The shipped `single_name_cap`, `scaffold.py:284` and every constraint an author
  writes stay **unchanged**: they keep comparing strictly and keep reporting `measured`/`bound`/
  `excess`, and the framework buckets the result in one place. A tolerance on `ConstraintBounds`
  was also the one shape that could leak into `project` and widen the feasible set the optimiser
  works in; this cannot.
- **The record reports `checked` / `held` / `within_tolerance` / `breached`**, the worst excess in
  each of the last two, and the tolerance used. `ok` is false only when `breached > 0`. This is
  what makes a generous default safe: nothing is hidden, it is filed.
- **Known looseness, accepted:** on a small bound (0.5%) the 10bp floor is a fifth of the bound.
  The alternative is a false alarm on a small book, and an author who wants it tighter overrides.

**Status when filed:** OPEN. Found 2026-09-04 by `kwam-enhanced-index/vqapr-enhanced-index-3` (C6): 40 of 82
rebalances recorded as violations of a cap the optimiser had respected, worst excess 0.01%p.
Confirmed in source on this branch.

**Touches:** `src/vqapr/authoring.py:1056-1096` (`ConstraintFinding`: `passed`, `measured`, `bound`,
`excess` — no tolerance); `src/vqapr/constraints/builtin/single_name_cap.py:173-208`
(`_worst` offends on `size > ceiling`, strictly; `monitor` sets `passed=not offenders`);
`src/vqapr/flow/records.py:300-336` (the contract block's `held`/`checked` and the `cause`/`fix` it
writes).

## What happens

`optimize` places weights on the `QUANTUM` grid and the book then executes in whole lots, so the
realised weight differs from the target by the grid resolution. `monitor` measures the realised
book against the same bound with a strict comparison, and any positive difference is a breach:

```python
if size > ceiling:
    offenders.append(instrument)
...
passed=not offenders, excess=max(measured - bound, Decimal(0))
```

There is no tolerance anywhere in the path — not on the finding, not on the bound, not on the
constraint. So a 0.0001 overshoot that is arithmetically unavoidable lands in the record as a
violation, in the same counter as a genuine one:

```
contract: {single_name_cap: {held: 42, checked: 82, ok: false,
           cause: "40 of 82 check(s) did not hold",
           fix: "loosen single_name_cap to a bound the book can stay inside, or change the
                 strategy so what it holds satisfies it"}}
```

`held 42/82` reads as *half this run violated its cap*. What happened is *every rebalance complied,
to within the resolution of the grid the framework itself put the weights on* — and, separately,
that the book drifted 4.89%p past the cap intra-month, which is the real breach and the one that
should be visible. The two are added together.

The `fix` then points the wrong way: loosening the bound or changing the strategy does not remove a
rounding residue, and doing either in response to this report would be acting on a fact that is not
true.

## Why the author cannot fix it in their own constraint

`passed` is the constraint's to set, so in principle a constraint author can compare against
`bound + tolerance` and be done. Two things stop that being the answer.

- **The shipped constraint has the defect.** `single_name_cap` is the one most projects use, and it
  offends strictly. So does `scaffold.py:284`, the template every new constraint is copied from.
- **Every author then re-derives the same distinction.** The reporter's `measure_ensemble.py` had to
  split rebalance days from the days between them and report each one's worst excess separately,
  purely to recover the fact the record had folded away. That post-processing is not project-
  specific; it is the framework's grid meeting the framework's comparison.

## What to do

Needs an owner ruling on where the tolerance lives, of which the two candidates are:

1. **On the finding.** `ConstraintFinding` gains `tolerance`, `passed` is judged against
   `bound + tolerance`, and the record reports it — so a reader sees both that it held and by what
   margin it was allowed to.
2. **On the bound.** A `Constraint` declares the resolution it is measured at when it states its
   bounds, and the comparison is made once, in one place, for every constraint.

Either way the record should stop conflating the two populations: a breach within tolerance and a
breach beyond it are different facts, and `held`/`checked` currently has room for only one of them.
`051` is the issue that made this block report anything at all; this is the next question it
raises.

## Related

`014` (one rule, one book, three answers — the reason `_worst` measures in one member), `051` (the
contract block, closed by record `130`), record `086` in `docs/implementations/` (a refusal that
names what breached it — cited from `authoring.py` and `constraints/findings.py`), `085` (the other
counter that folds two facts into one).
