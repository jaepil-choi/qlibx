# 130 — one constraint declaration, two consumers

**Closes:** `docs/issues/archive/051`. Half-closes `docs/issues/archive/036` (the Constraint third of it).
**Files:** `docs/issues/archive/052`.
**Step:** M1.1 of `docs/refactoring/2026-09-02-the-convergence-campaign.md`.
**Authority:** `docs/vqapr-prd.md` §7, §7.1 and `docs/vqapr-architecture.md` §5.7, both rewritten by
owner ruling in commit *"A constraint has two consumers, not three"*.

## Why this exists

A constraint did three things. It bounded construction, it scored the decision the moment it was
made, and it observed the committed account. The owner ruled that the middle one is not a thing:

- **Construction is best effort.** The strategy builds the best portfolio the limits allow. Whether
  it managed to is not a separate verdict.
- **Monitoring is fact.** What is actually held either exceeded a limit or did not.

Scoring the decision sat between them and belonged to neither. It also had two defects that could
not be fixed while it existed.

**It could not see the breach that matters most.** Rounding a weight into whole shares moves it, and
no fills exist at decision time (`UC-CONSTRAINT-ADJUST-001`). The member that judged the decision
structurally missed exactly the case the framework's own use case says to watch for.

**Two scorers can disagree.** `docs/issues/archive/014` measured it: the shipped cap read a signed weight in
one member and an absolute one in the other, so a proposed `-0.30` passed the check before execution
and was reported as a violation by the check after it, while the box handed to the optimiser had
excluded it outright. One rule, one book, three answers. That was closed by making the two members
share a helper — discipline, not structure. There is one place to measure now, so it cannot recur.

## What changed

### The contract has two members

An author declares reads, projects bounds, and measures a committed account. `constraint_id` stays,
declared once and checked at load against the registration; what went is the *repetition* — a
finding no longer restates the id the framework is holding while it makes the call.

**A finding carries what a breach needs and nothing more:** the rule, the limit, the measured value,
the excess, and the names that breached. Read provenance is deliberately absent — following every
read into every judgement makes observation heavy, and heavy observation gets run less often, which
is the opposite of what a monitoring layer is for. What was read is a fact about the window, which
already records it, and a fact about the run rather than about each finding.

`offenders` is a field rather than a `details` key, for two reasons. `details` admits portable
scalars so a diagnostic mapping survives a round trip, and a tuple is refused. And it is the one
thing a breach cannot be reported without, so a message must not depend on a convention inside a
free-form mapping.

### A breach no longer ends a run

The scoring member was a hard gate: a failing verdict raised, and the run stopped at that
occurrence. It does not. A decision outside the limits proceeds, executes, and shows up in the
monitoring finding for the account it produced.

This is the same rule as a halted name not stopping a rebalance (`013`) and an unfill being recorded
with a reason rather than aborting (`039`): **economic facts are recorded, and progress is not
blocked.** Stopping also hid what the strategy went on to do for the rest of the period.

`tests/cli/test_commands.py::test_new_constraint_emits_a_rule_that_registers_and_runs_unedited`
drives it end to end through the CLI: a scaffolded 20% cap, a workspace holding one instrument, a
strategy proposing all of it — the run completes, and the record names the breach.

### The third role reads like the other two

`Constraint` gains `inputs()` and reads through the same `read(alias)` that records `126` and `128`
gave `DataModel` and `StrategyModel`, over a context that joins them in `models/contexts.py`. It no
longer receives a `ModelWindow`, an `EconomicPortfolioIntent`, an `AccountSnapshot` or a `MarkBatch`
— four framework types no other extension point sees.

**Projection lost the account it never used.** The authoring contract had carried one, which meant
the member that runs before any decision exists was handed the committed account. The engine never
offered it. Where two contracts disagree about how much a member may see, the narrower is right
(architecture §2.2): monitoring receives it as its own argument.

**And the account view gained what a weight rule needs.** It carried quantities and one aggregate
NAV; a weight is value over NAV, so no weight-based rule could be written against it at all — which
is what both shipped rules are. It now carries marked values, with `value()`, `weight()` and
`weights()`. Absence is `None` rather than an empty mapping: a Strategy callback fires before its
occurrence is valued, and an empty book would make every weight rule report a confident zero.

### Three classes became one, and the loader stopped disagreeing with itself

`Constraint`, `ConstraintBounds` and `ConstraintFinding` are now one object each, exported under
both `vqapr.public` and `vqapr.authoring`. `load_constraint` accepts what the package tells an
author to write; it used to refuse it while `load_strategy_model` adapted the same contract inward
(R5 of the post-Step-07 review). `tests/extension/test_one_authoring_surface.py` asserts the
identity for the three that converged, and still asserts the divergence of the two that have not.

### The run record reports its constraints for the first time

`docs/issues/archive/051`. The block walked lifecycle entries asking each for an `evidence` attribute; a
lifecycle entry has `kind` and `detail`, and the evidence is the `detail`. The lookup returned
`None` every time and the loop never ran, so **every record ever written carried `{}` there**. The
only test asserted the key existed, which it did.

It now walks the monitoring occurrences' reports, which is where the answer belongs: whether a limit
held is a question about the committed account. **`held`/`checked` are not comparable across this
change** — they were meant to count decisions once per callback and now count observations once per
monitoring occurrence, which is a different cadence.

## Trade-offs

**A breach is reported later.** It surfaces at the next monitoring occurrence rather than at the
decision. That is the cost of measuring the book instead of the plan, and the plan could not see the
rounding breach anyway. A run with no monitoring agenda observes nothing — which the record says, by
reporting `checked: 0` and `ok: false` rather than silence.

**Existing constraints break.** Three members become two, the bounds fields are renamed, and a
finding no longer takes an id. There is no compatibility shim: two spellings of one contract is the
defect `036` is about, and a release that accepted both would re-create it.

## Validation

```
uv run ruff check src/                           All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs         1295 passed, 14 deselected
PYTHONUTF8=1 uv run pytest tests/ -q -m "" -rs   1309 passed
```

Branch parent `develop @ 38fef4ba`, measured rather than quoted: **1294 passed, 14 deselected**
fast; **1308 passed** full.

**Showcases: 4 of 9 complete, unchanged from the branch point.** Measured both ways — with this work
applied and with it stashed — and the same five fail either way, for causes that predate it
(`docs/issues/archive/052`). `show_003` regressed mid-change and was repaired; it passes.

Directed checks:

- The emitted constraint template was rendered and driven outside the suite: it projects, and it
  monitors an account view naming the offender. 83 lines, down from 99.
- `tests/characterization/refusal_codes.py`'s stale-signature fixture had stopped provoking its own
  defect — renaming the member made the class abstract, so the load refused before the signature
  check ran. Restored to a wrong *arity*, which is what it is for. The file's own comment warns
  about exactly this, and the refusal baseline is unchanged as a result.
- `tests/boundaries/test_a_deferred_import_states_its_reason.py`'s ceiling lowered 37 → 36, as that
  test instructs when a change removes a deferred import.
