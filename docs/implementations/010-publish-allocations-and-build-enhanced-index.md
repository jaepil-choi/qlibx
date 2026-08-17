# 010 — Publish run allocations and build an enhanced index

## Why this exists

A strategy could compute an allocation but could not hand it to another strategy. That blocked two
things the PRD already promised: an ensemble that combines several stored alpha results, and an
enhanced index that subscribes to a stored alpha and executes itself.

The requirements interview and the consensus plan both converged on one idea that made the rest
small: **an allocation input is defined by declared invariants, not by provenance.** Registered
point-in-time data and a published run output are the same kind of input whenever the invariants
hold. A benchmark therefore needs no synthetic run, an alpha result needs no special reader, and
both are consumed through the ordinary `DataRequirement` path.

That collapsed an entire planned data contract and three planned subsystems.

## What was built

| Deliverable | Location |
|---|---|
| Canon amendment (module tree, `optimize()` scope, numeric grid ownership) | `docs/vqapr-architecture.md` |
| Dated benchmark fixture and its extraction | `scripts/extract_dw_fixture.py`, `tests/fixtures/real/` |
| Exact closed-form projection | `src/vqapr/portfolio/optimize.py` |
| Allocation input contract | `src/vqapr/portfolio/allocation.py` |
| Shipped constraints and their discoverability door | `src/vqapr/constraints/builtin/` |
| Allocation publish writer | `src/vqapr/flow/materialize.py` |
| Real-data acceptance suite | `tests/acceptance/test_enhanced_index.py` |
| End-to-end showcase | `showcases/show_005_enhanced_index/` |

## How it works

**Publication reuses the materialize machinery.** The staging, validation, atomic exposure, rollback
and registration body is now one shared helper that both `materialize` and `publish_run_allocation`
call. A second publication path would have been a second publication authority, and the two would
have drifted. The lineage payload was split into a shared envelope (`schema_version`, `operation`,
`output`, `instruments`) with the operation discriminating a provenance block, so `materialize` keeps
`component` and `invocations` while an allocation carries `run`, and neither fabricates the other's
keys. `datamodel.materialize` output stays byte-identical.

**The stamp is derived, never chosen.** `publish_run_allocation` is driven from callback evidence and
stamps through `derived_available_at` over the callback's own recorded accesses, so a producer cannot
advertise a decision earlier than the inputs that justified it.

**The projection is exact, not approximately exact.** Without a cost term, a turnover penalty or an
exposure mapping, the problem is a box projection onto a budget hyperplane, parameterised by one
multiplier: `w_i = clip(desired_i - lam, l_i, u_i)`. Sorting the `2n` breakpoints locates the
bracketing segment where the clipped sum is affine, so the multiplier is solved exactly in
`fractions.Fraction`. There is no iteration, so no precision budget and no tolerance to tune. The solve path imports no
solver package; note that `cvxpy` is already a declared project dependency for other work, so the
claim is that this path does not use one, not that the project has none.

**The weight-sum invariant is coverage-scoped.** A four-name slice of a two-hundred-name index sums
to roughly `0.549`. Requiring `1` would reject genuine vendor data; renormalising would restate the
vendor's numbers as something they are not. The uncovered remainder is cash.

**Long-only is emergent.** A signed alpha enters the construction unchanged. `no_short`, intersected
with a single-name cap that lifts each name's ceiling to `max(cap, benchmark_i)`, removes the short
leg. Requiring a long-only input would have broken the long-short → ensemble → enhanced-index chain.

## Trade-offs

**Numeric grids are owned in canon, not in code comments.** Three grids exist: a vendor normalization
scale at the registration boundary, the canonical `1e-12` grid for every package-produced weight, and
a working precision inside `optimize()` only. The architecture table names each one's boundary *and*
what it explicitly does not own — the third row records that the working precision does not reach
`validate_economic_intent`, which is a real trap: a `localcontext` expires at the block edge while
the validator runs in the caller's own context.

**Frozen names are guarded at the entrance, not rounded at the exit.** Quantizing a frozen weight
would break frozen invariance. Instead, a frozen `current[j]` finer than the grid is refused by name.
The consequence is stronger than precision would give: every returned weight then carries at most 12
decimal places, so the validator's regrouped sum never rounds and the associativity problem does not
shrink — it disappears.

**Cash is the only residual sink.** Adding a rounding residual to an instrument could push it past a
bound the caller was promised would hold.

**Shipping builtin constraints does not close an open extension point.** The discoverability surface
resolves shipped constraints by name and path; no `isinstance` gate was added to `load_constraint`.
An identity gate would reject user-authored constraints, and would fail on the package's own builtins
anyway, because a path-loaded component is re-executed under a fingerprinted module name and is a
distinct class object.

## Deliberately not built

No catalog, publication or lineage subsystem and no `ArtifactRef` — `materialize` already published
atomically with lineage, and Architecture §4.2 forbids an `ArtifactRequirement` because computed
results are datasets. No active-weight field on the intent: active is derivable, and a second field
would create two ways to state one allocation. No ex-ante tracking-error constraint: a portfolio
quadratic has no representation in per-instrument bounds, so tracking error is recorded post hoc by
monitoring only. No cost, turnover penalty or look-through in `optimize`. No package-supplied
ensemble combination helper — equal weighting, IC weighting and risk parity belong to user strategy
code. The ensemble's own run is a later milestone; this one proves multi-input subscription.

## Validation

- `uv run pytest -q` — 279 passed (from 226 at the start of the milestone).
- `uv run ruff check src tests scripts showcases` and `ruff format` — clean.
- `uv run python showcases/show_005_enhanced_index/run.py` — 22 sessions, two subscribed allocation
  inputs, alpha minimum weight `-0.02`, 21 frozen occurrences returned verbatim, 40 whole-share
  fills, fill-journal replay matching running cash exactly, tracking error 1.045% → 0.642%, and two
  clean runs producing identical SHA-256 manifests.
- Known open findings from the boundary review are recorded in the Ultragoal ledger and are not
  closed by this record; see the milestone's review blockers.
- Acceptance criteria are discharged in `tests/acceptance/test_enhanced_index.py`, each test naming
  the criterion it proves, all reading committed real market data.
