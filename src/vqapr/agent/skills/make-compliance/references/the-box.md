# The box is the strategy's

## Why it is a kit and not a component

Construction is best effort: when the portfolio the signal wants and the portfolio a limit allows
differ, the strategy builds the second. Best effort is discretion, and discretion is the
strategy's, so there is nothing for the framework to guarantee about it — and a component the
framework ran on the strategy's behalf would be a second, invisible strategy.

So the box is built inside `decide()`, by the strategy, from pure functions.

## The kit

| function | returns | meaning |
|---|---|---|
| `no_short(names)` | `(lower, upper)` | `0 ≤ w_i ≤ 1` for every name |
| `single_name_cap(names, benchmark, cap)` | `(lower, upper)` | `|w_i| ≤ max(cap, benchmark_i)`; a name absent from `benchmark` takes `cap` |
| `intersect(box, box, ...)` | `(lower, upper)` | lower bounds take the max, upper the min, name by name |

Each box is a pair of `{name: Decimal}` mappings covering the same names, which is exactly what
`optimize(lower=..., upper=...)` takes. A box that misses a name is refused, because a missing
bound would silently widen the feasible set rather than fail.

Long-only is **emergent**: `no_short` floors at zero, `single_name_cap` mirrors its ceiling on
the short side, and only their intersection is long-only-with-a-cap. Neither alone is.

## The data is the strategy's subscription

`single_name_cap` needs the index weight per name. The strategy reads it through its own
`inputs()` / `requirements()` and validates it as it sees fit — `validate_allocation` with
`AllocationSign.LONG_ONLY` is the shipped check — before handing it to the kit. This is what puts
the dependency on the strategy, where `vqapr show model` and `vqapr check` can see it, rather
than hidden inside a rule's declaration.

## What this costs

The framework no longer preserves a per-rule "before and after" of construction. If a paper needs
to show what a limit removed from the signal, the strategy records it — `self.recorder` and a
declared table — the way it records anything else it wants kept.
