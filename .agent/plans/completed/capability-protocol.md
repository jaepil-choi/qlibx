# Give the four capability cycles one shared protocol

Status: complete

## Purpose

Four capabilities hand-write the same declare/evidence/evaluate/plan cycle:
`alpha.registry.plan_operation`, `alpha.exposure.plan_exposure`,
`profiles.plan_execution_profile`, and `strategy_manifest.capability.plan_strategy_binding`.
Each rebuilds the evidence loop, re-pairs `evaluate_requirements` with `make_plan`, and
invents its own wording for the same facts. A fifth capability would be a fifth copy, and
the copies have already drifted: two of them implement the *identical* "are the caller's
inputs supplied" rule with different strings and different `details` keys.

## Scope and non-goals

In scope: a probe-based evidence protocol in `qlibx/requirements.py`, and converting all
four call sites to it.

Non-goals:

- No change to `evaluate_requirements` semantics. It is the pure evaluator and stays as is.
- No new capability, and no change to which requirements any capability declares.
- No extraction of the "refuse when the plan is not ready" guard. See Discoveries: the
  layering forbids it, and working around that would be worse than the four two-line copies.

## Acceptance criteria

- `requirements.py` still imports nothing from `qlibx`
  (`test_architecture.py::test_kernel_has_no_intra_package_dependencies`).
- `alpha` still depends only on `errors` and `requirements`
  (`test_architecture.py::test_alpha_is_a_pure_domain_package`).
- No capability builds a `RequirementEvidence` by hand.
- `uv run pytest` matches the baseline: 128 passed plus the one pre-existing `cp949`
  acceptance failure. `ruff check` and `ruff format --check` clean.
- New protocol functions have direct tests in `tests/test_requirements.py`.

## Repository context

`qlibx/requirements.py` (259 lines, layer 0) holds the contracts, `evaluate_requirements`
and `make_plan`. The four cycles:

| Call site | Evidence rule | Lines |
|---|---|---|
| `alpha/registry.py:168` `plan_operation` | required_inputs minus supplied | ~30 |
| `alpha/exposure.py:204` `plan_exposure` | role in supplied — *same rule, different words* | ~35 |
| `profiles.py:132` `plan_execution_profile` | catalog lookup, three failure reasons, plus a special-cased clock | ~47 |
| `strategy_manifest/capability.py:83` `_input_evidence` | binding match, dataset kind, field mapping, inventory | ~95 |

The last two have genuinely distinct evidence logic and keep it. What they share with the
first two is the loop, the labelling, and the evaluate-then-plan pairing.

## Milestones

- [x] M1: Add `Finding`, `gather_evidence`, `supplied_roles_probe`, `plan_capability` to
      `requirements.py`, with direct tests.
- [x] M2: Convert `alpha/registry.py` and `alpha/exposure.py` (the two that duplicate one
      rule) to `plan_capability` + `supplied_roles_probe`.
- [x] M3: Convert `strategy_manifest/capability.py` and `profiles.py` to probes.
- [x] M4: Full validation, implementation record.

## Progress

Complete. Net `+324 / -150` across six files, of which `+132` is the protocol and `+80` is
its tests — so the four call sites shed roughly 100 lines of duplicated bookkeeping.

`RequirementEvidence` is now constructed in exactly one place in the package
(`requirements.gather_evidence`); before, four capabilities built it by hand.

## Discoveries

- **`plan_operation` and `plan_exposure` compute the identical predicate.** Every exposure
  requirement declares exactly one alternative whose `required_inputs` is `(role,)` and whose
  `requirement_id` equals the role, so `set(required_inputs) - supplied` and
  `role in supplied` are the same test. Two implementations, two vocabularies, one rule.
- **The "refuse when not ready" guard cannot be extracted.** All four capabilities end with
  `if not plan.ready: raise requirement_gap(plan.resolution.to_dict())`. A shared
  `require_ready` needs both `errors` and `requirements`, but
  `test_kernel_has_no_intra_package_dependencies` forbids either kernel module from importing
  the other, and `test_alpha_is_a_pure_domain_package` forbids `alpha` from importing a new
  layer-1 module that could hold it. The four copies stay. This is the architecture tests
  doing their job, not an obstacle to route around.
- No test pins any evidence `reason` string or `details` key, so the protocol can unify the
  wording. `analyze_exposure` does surface `reason` in `UnavailableOutput`.

## Decision log

- **Probe, not subclass.** A capability supplies
  `(requirement, alternative) -> Finding | None`; the protocol owns the loop and the
  labelling. Returning `None` declines an alternative, which `evaluate_requirements` already
  reads as absent evidence — so a capability never has to invent a reason for a question it
  does not answer.
- **`Finding` carries no IDs.** `RequirementEvidence` needs `requirement_id` and
  `alternative_id`; the probe is already being *told* both, so making it repeat them back is
  what produced the eight-times-repeated `RequirementEvidence(requirement_id,
  "registered_binding", False, ...)` in `strategy_manifest`. The protocol labels the answer.
- **One behavior change, deliberate: evidence `details` uses `supplied_roles`/`missing_roles`
  in both alpha capabilities**, where `registry` said `provided_inputs` and `exposure` said
  `available_inputs` for the same fact. The public keyword arguments and each plan's own
  `parameters` dict keep their existing names, so no caller breaks; only the shared evidence
  document becomes consistent. An agent reading two plans should not find one fact under two
  names — that inconsistency is the thing this task exists to remove.
- **`profiles` keeps evaluate-then-plan as two steps.** Its warnings depend on the
  resolution, so it uses `gather_evidence` but not `plan_capability`. Bending
  `plan_capability` to accept a resolution-dependent warnings callable would make the common
  case worse to read for one caller's benefit.

## Validation

Baseline: `128 passed, 1 failed` at `40e6029`, the failure being the pre-existing Windows
`cp949` console-codec error in `tests/acceptance/test_p0_p1_agent_journey.py`.

After: `132 passed, 1 failed` — the same pre-existing failure, plus the four new protocol
tests. No existing test was edited. `ruff check` and `ruff format --check` clean.

Each new test was mutation-checked:

| Mutation | Fails |
|---|---|
| `gather_evidence` iterates `alternatives[:1]` | the labelling test and the `supplied_roles_probe` selection test |
| a declined (`None`) probe answer becomes a fabricated `Finding(False, "declined")` | the decline test |

The first mutation is the one worth having: a protocol that only asked about the first
alternative would still make every current capability pass, because three of the four
declare exactly one alternative per requirement. Only `market_return` in the test fixture
has a fallback path, and only that test would notice.

## Risks and recovery

- **Over-abstraction.** The protocol must not swallow the evidence *decisions* in `profiles`
  and `strategy_manifest`, which are genuinely different. It owns the loop and the labelling
  only. If a milestone starts adding flags to `plan_capability` to accommodate one caller,
  that is the signal to stop and let that caller stay explicit.
- Recovery: one commit per milestone group on `exp/one-shot` after `40e6029`.

## Next action

None. Move this plan and `strategy-manifest-split.md` to `.agent/plans/completed/` when the
next task starts.

Open item deliberately left: the four copies of
`if not plan.ready: raise requirement_gap(plan.resolution.to_dict())`. Extracting it needs a
home that can see both `errors` and `requirements`, which the kernel and pure-domain rules
forbid. Resolving it properly means deciding whether `alpha` may depend on a layer-1
capability module — an architecture question, not a refactor, and one for the user to call.
