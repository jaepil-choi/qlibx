# 092 — `optimize` refuses the bounds the shipped `single_name_cap` produces

**Status: CLOSED 2026-09-10 -- record `218`.** The surface the report names (`Constraint.project`,
`call.constraint_bounds`) left in 0.10.0 (record `208`), and the defect moved with it into the kit:
`vqapr.portfolio.bounds.single_name_cap` returned `max(cap, benchmark)` at the benchmark's own
exponent. The kit now rounds every bound inward onto the `1E-12` grid -- ceilings down, floors up --
in `single_name_cap` and `intersect`, so the direction lives where "bound" is defined; `optimize`'s
refusal names the kit and the two directions; `the-box.md` says so. Left open as a follow-up under
`094`: a typed refusal raised by a package helper inside a callback is classified 500 by frame
origin and should be a 422.

Filed as `report-2026-09-09-optimize-refuses-the-shipped-constraints-own-bounds.md`; numbered on
triage.

| | |
|---|---|
| vqapr version | `0.9.0.dev1` |
| installed from | `../../vqapr/dist/vqapr-0.9.0.dev1-py3-none-any.whl` |
| reported | 2026-09-09 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12 / Windows 11 |

## What I was doing

Building an enhanced-index StrategyModel that must respect `w_i <= max(10%, index weight)`. The
shipped `single_name_cap` projects that bound, `call.constraint_bounds` merges it, and
`vqapr.public.optimize` projects the desired book onto it. All three are the package's.

## What I expected

That the bounds one shipped component produces are accepted by the shipped optimiser they exist
to feed. `project` "returns the box ... the optimiser needs a feasible region"
(`references/project-and-monitor.md`), so the box and the optimiser are two halves of one path.

## What happened

`optimize` refuses them. The bound is `max(cap, benchmark_weight)`, the benchmark weight arrives
from a registered dataset as a DOUBLE, and a DOUBLE converted to `Decimal` carries an exponent of
-16 -- finer than the canonical 1E-12 grid `optimize` enforces.

Reproduced at library level, no run required:

```python
from decimal import Decimal
from vqapr.public import optimize
import pool                      # this project's reader for a materialized dataset

f = pool._read("kospi-weights-values", ["available_at", "instrument", "weight"])
w = Decimal(str(f[f.instrument == "A005930"].iloc[-1]["weight"]))
bound = max(Decimal("0.10"), w)          # exactly what SingleNameCap.project computes

optimize(desired={"A005930": Decimal("0.3")}, current={},
         lower={"A005930": Decimal(0)}, upper={"A005930": bound},
         cash_range=(Decimal(0), Decimal("0.02")))
```

    kospi weight  : 0.2690387918366073
    max(10%, w)   : 0.2690387918366073  exponent -16

    REFUSAL OptimizeRefusal
    upper['A005930'] has exponent finer than the canonical grid 1E-12; coarser bounds are
    accepted, finer ones are not

In a run the same refusal arrives as:

    "code": "strategy.callback.intent", "status": 502,
    "observed": "upper['A005930'] has exponent finer than the canonical grid 1E-12; coarser
                 bounds are accepted, finer ones are not"

## Reproduction

Reproduced every time (12 of 12 strategies, then the four-line library snippet above):

1. Register `single_name_cap` bound to any dataset whose weight field is DOUBLE.
2. In `decide()`, pass `call.constraint_bounds.upper_weights` straight to `optimize`.
3. Refused on the first callback whose cross-section contains a name above the 10% floor.

## Impact

Worked around. The caller quantises before passing the box on, and the rounding DIRECTION is not
free -- an upper bound must round down and a lower bound up, so rounding can only tighten a
mandate, never loosen it:

```python
upper = {n: v.quantize(Decimal("1E-12"), rounding=ROUND_FLOOR)
          for n, v in bounds.upper_weights.items()}
lower = {n: v.quantize(Decimal("1E-12"), rounding=ROUND_CEILING)
          for n, v in bounds.lower_weights.items()}
```

The hazard is that the direction is the caller's to get right, on a value the caller did not
compute, for a rule that is a legal limit. Rounding an upper bound the other way is a compliance
breach that nothing would report, because the book would be inside the box it was given.

## What would have prevented it

`optimize` quantising a bound it is handed -- conservatively, the way the workaround does -- or
`ConstraintBounds` quantising on the way in, since it already validates into a `CrossSection`.
Either puts the rounding direction inside the package that owns the meaning of "bound". Failing
that, the refusal naming the fix, and `project-and-monitor.md` saying that a projected box needs
quantising before the shipped optimiser will take it.
