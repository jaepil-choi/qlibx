# 080 — A cap bounds size, and says nothing about sign

`SingleNameCap` gave three answers about one book. For `{A: +0.10, B: -0.30}` at a cap of `0.2`:

| member | when it runs | verdict on `B` |
|---|---|---|
| `project` | before, to build the optimiser's box | **forbidden** — floor was `Decimal(0)` |
| `validate_intended` | before execution, on the proposal | **permitted** — `-0.30` is not `> 0.2` |
| `evaluate` | after execution, on the marked book | **violated** — `abs` made it `0.30` |

So a signed intent passed the gate that runs *before* the trade and was reported as a violation by
the check that runs *after* it, while the box handed to the optimiser had excluded it in the first
place.

## The design already said which one was wrong

`NoShort`'s docstring:

> This is the constraint that makes long-only an **emergent property of the constraint set** rather
> than a precondition on an input. A signed alpha can enter the enhanced-index construction
> unchanged; it is **this** projection, intersected with the others, that removes the short leg.

A second constraint quietly removing the short leg makes that claim false. It also made a signed
book with a cap **inexpressible**: every constraint set containing this one was long-only whether
or not anyone asked for it.

Same shape as issue `013`, fixed one commit earlier: the intent is written down in one place and
contradicted in another.

## The fix is three lines and one `abs`

`project` returns a symmetric box, mirrored against the **ceiling** rather than against `cap`. The
ceiling is `max(cap, benchmark)` because a name already heavier than the cap may be held at its
index weight; the same reasoning on the other side gives the same magnitude with the other sign.

`_worst` takes `abs(weight)`. That is the one place both judgments come through — `validate_intended`
was handing it signed weights and `evaluate` absolute ones — so measuring size *there* makes the two
agree by construction rather than by two call sites remembering to.

`evaluate` already passed `abs(mark.value)/nav`, so the change is idempotent on that path.

## Nothing long-only moves

Verified against `merged_constraint_bounds`, which takes the max of lower bounds and the min of
uppers:

```
NoShort (0,1) ∩ symmetric cap (-c,+c)  ->  (0, c)
NoShort (0,1) ∩ old cap        (0,+c)  ->  (0, c)      IDENTICAL

symmetric cap alone                    ->  (-c, +c)    <- newly expressible
```

`show_005_enhanced_index` registers **both** builtins, so its behaviour is unchanged. What changes
is that a project wanting a signed book with a size cap can now have one, which it could not
before.

## Validation

```
uv run pytest tests/ -q -m ""    # 1332 passed, clean
uv run pytest tests/ -q          # 1318 passed, 14 deselected
uv run ruff check src/vqapr/ tests/ showcases/   # 15, compared entry by entry: none introduced
```

- `test_the_cap_gives_one_answer_about_a_short_across_all_three_members` drives all three against
  the real benchmark projection at twice the ceiling and at half of it, asserting each member gives
  the same verdict at each size. Both directions, so a constraint that refused everything would
  fail as surely as one that permitted everything.
- `test_long_only_emerges_from_intersecting_the_two_builtins` gained the assertion that makes its
  own title true: the cap alone does **not** floor at zero, and its floor mirrors its ceiling.
  Without that, the test held whether or not `NoShort` was in the set.

## The scaffold's citation is now true

`vqapr new constraint` emits a pure size cap, corrected in record `073` when the completion gate
found the same three-way disagreement in it. Its comment cited `SingleNameCap` as the shipped
size-only precedent, the cleaner lane checked the citation rather than the claim, and the citation
was withdrawn because the cited constraint did not do what the sentence said.

It is restored, because the constraint now does. The package no longer ships a teaching example
that contradicts the builtin it points at.
