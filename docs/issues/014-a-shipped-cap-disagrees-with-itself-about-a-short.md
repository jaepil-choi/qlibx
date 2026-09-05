# 014 — A shipped cap disagrees with itself about a short

> **Structurally impossible as of 2026-09-02, record `130`.** This was closed by making the two
> members that measured share one helper -- a discipline, which the next constraint an author
> writes is free to ignore. There is now **one member that measures**: the one that judged the
> decision was removed (PRD §7.1, architecture §5.7), so a second answer has nowhere to come from.
> The regression test moved with it and is now
> `test_the_cap_gives_one_answer_about_a_short_across_both_members`.

**Status: CLOSED 2026-08-29** by
`docs/implementations/080-a-cap-bounds-size-and-says-nothing-about-sign.md`.

Option 1 was taken — a pure size cap — and the reason it was not a coin toss is that `NoShort`'s
docstring already claimed to be *the* projection that removes the short leg, which a second
constraint quietly removing it makes false. `project` returns a symmetric box mirrored against the
ceiling, and `_worst` measures `abs`, so all three members give one answer.

The benchmark asymmetry this file flagged as the reason a symmetric version was non-mechanical
resolved the same way: the floor mirrors `max(cap, benchmark)` rather than `cap`, on the same
reasoning that sets the ceiling.

Long-only behaviour is unchanged, verified against `merged_constraint_bounds`:
`NoShort ∩ symmetric cap` is `(0, ceiling)`, identical to before. `show_005` registers both, so it
is untouched. What is new is that a signed book with a size cap is expressible at all.

The original report follows unchanged.

---

**Status when filed:** open. Found 2026-08-28 by the cleaner lane of the Slice B completion gate,
while
checking whether a new scaffold's docstring cited its precedent accurately. It did not, and the
reason is that the precedent has the defect the scaffold was just corrected for.
**Touches:** `src/vqapr/constraints/builtin/single_name_cap.py`.

## The three members answer differently

For a proposed book `{A: +0.10, B: -0.30}` at `cap = 0.2`:

| member | line | test | verdict on `B` |
|---|---|---|---|
| `project` | `:120-126` | lower bound `Decimal(0)` | **forbidden** — the feasible set has no room for a short at all |
| `validate_intended` | `:141-150` | raw `target.weight` through `_worst`, which tests `weight > ceiling` | **permitted** — `-0.30` is not `> 0.2` |
| `evaluate` | `:159-171` | `abs(mark.value) / nav` | **violated** — `0.30 > 0.2` |

So a signed intent passes the gate that runs **before** execution and is reported as a violation by
the monitoring check that runs **after** it, while the projection the optimiser is handed forbade it
in the first place. One rule, one book, three answers.

## Why it surfaced now

`vqapr new constraint` emits a single-name cap, and its first version had exactly this shape —
`project` flooring at `0`, `validate_intended` signed, `evaluate` absolute. The completion gate's
architect lane caught it with the worked example above, and it was corrected to a pure size cap:
symmetric bounds, `abs()` in both checks, with the sign rule left to `NoShort`.

The scaffold's comment then justified that design by citing `SingleNameCap` as the shipped
size-only precedent. The cleaner lane checked the citation and found the cited constraint does not
do what the sentence claims. The citation is fixed. The constraint is not.

## Which is wrong is a decision, not an oversight

Two coherent shapes, and `SingleNameCap` is currently neither:

1. **A pure size cap.** `project` returns `-cap`/`+cap`, both checks measure `abs`. The sign rule
   belongs to `NoShort`, and constraints intersect — `merged_constraint_bounds` takes the max of
   lower bounds and the min of uppers, so `NoShort (0, 1)` ∩ `cap (-cap, +cap)` = `(0, cap)`. This
   is what the scaffold now does.
2. **A long-only cap, stated as such.** Keep the `0` floor, and make `validate_intended` test
   `weight < 0 or weight > cap` so it agrees with both neighbours.

The second is a smaller edit and preserves current behaviour for long-only books, which is every
book the shipped tests exercise. The first composes better and is what a reader of the scaffold
will now expect the shipped constraint to look like.

**Note the benchmark asymmetry** before choosing: this cap's upper bound is
`max(self._cap, benchmark[instrument])`, so its ceiling is not a constant. A symmetric version has
to decide what the lower bound is when the benchmark exceeds the cap — `-max(cap, benchmark)` is
the mechanical answer and may not be the intended one.

## Why it was not fixed when found

Changing a shipped constraint's behaviour is outside Slice B, whose contract is `RECORD_FIELDS` and
the registration envelope. It is also not a refusal-shape fix: it changes which books a run
accepts, which is a product decision with a test surface of its own.

## Same class as issue 013

Both are two statements about one book that nothing reconciles — there, a venue's declared category
against the project's roster; here, one constraint's own projection against its own intent gate.
Neither is a crash, and that is what makes them expensive: every run involved completes `ok:true`.
