# 086 — a constraint has no tolerance, so quantisation residue is counted as a violation and the fix says loosen the bound

**Status:** OPEN. Found 2026-09-04 by `kwam-enhanced-index/vqapr-enhanced-index-3` (C6): 40 of 82
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
