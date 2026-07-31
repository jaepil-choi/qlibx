# One capability protocol instead of four hand-written cycles

## Why this change exists

Four capabilities each hand-wrote declare/evidence/evaluate/plan:
`alpha.registry.plan_operation`, `alpha.exposure.plan_exposure`,
`profiles.plan_execution_profile`, and `strategy_manifest.capability.plan_strategy_binding`.
Every one rebuilt the evidence loop, re-paired `evaluate_requirements` with `make_plan`, and
chose its own wording for the same facts.

The copies had already drifted, which is the concrete cost rather than the abstract one.
`plan_operation` and `plan_exposure` compute the **identical predicate** — every exposure
requirement declares one alternative whose `required_inputs` is its own role, so
`set(required_inputs) - supplied` and `role in supplied` are the same test — yet they
reported it as `provided_inputs` with one message and `available_inputs` with another. An
agent reading two qlibx plans found one fact under two names.

## What outcome it serves

A capability now supplies only the part that is genuinely its own: a probe answering "can
this alternative be satisfied right now". Labelling that answer with the requirement and
alternative it came from is bookkeeping the protocol does once.

`RequirementEvidence` is constructed in exactly one place in the package. Before, four.

## Behavior change

One, deliberate: the shared evidence `details` for caller-supplied inputs now uses
`supplied_roles` and `missing_roles` in both alpha capabilities, where `registry` said
`provided_inputs` and `exposure` said `available_inputs` for the same fact. `missing_roles`
is new information — previously neither reported which input was actually absent, only the
set that was present.

Public keyword arguments (`plan_operation(provided_inputs=...)`,
`plan_exposure(available_inputs=...)`) and each plan's own `parameters` dict keep their
existing names, so no caller breaks. Only the shared evidence document becomes consistent.

Evidence `reason` strings changed wording for the two alpha capabilities. No test pinned
them; `analyze_exposure` does surface them through `UnavailableOutput.reason`.

## Structural changes

`qlibx/requirements.py` gains four names, and still imports nothing — inside qlibx or out:

- `Finding` — a probe's answer about one alternative. It deliberately carries **no**
  requirement or alternative ID. The probe is handed both, so making it repeat them back is
  what produced the eight-times-repeated
  `RequirementEvidence(requirement_id, "registered_binding", False, ...)` in
  `strategy_manifest`.
- `gather_evidence(declaration, probe)` — asks the probe about every declared alternative
  and labels each answer. A probe returning `None` *declines* an alternative rather than
  refusing it, so a capability never invents a reason for a question it did not ask.
- `supplied_roles_probe(supplied)` — the rule the two alpha capabilities were each writing
  by hand.
- `plan_capability(...)` — gather, evaluate, plan.

`profiles` uses `gather_evidence` but not `plan_capability`, because its warnings depend on
what the resolution turned out to be missing. Bending `plan_capability` to take a
resolution-dependent warnings callable would make the common case worse to read for one
caller's benefit, so that caller stays explicit.

The evidence *decisions* in `profiles` and `strategy_manifest` are genuinely different and
were not touched — they became `_clock_finding`/`_role_finding` and `_input_finding`, which
return `Finding` instead of `RequirementEvidence` and are otherwise the same logic in the
same order.

## Trade-offs

- **The "refuse when not ready" guard stays duplicated four times.** All four capabilities
  end with `if not plan.ready: raise requirement_gap(plan.resolution.to_dict())`. A shared
  `require_ready` needs both `errors` and `requirements`, but
  `test_kernel_has_no_intra_package_dependencies` forbids either kernel module from importing
  the other, and `test_alpha_is_a_pure_domain_package` forbids `alpha` from importing a new
  layer-1 module that could hold it. Both tests are right; routing around them would trade a
  real boundary for two saved lines per site. Resolving it means deciding whether `alpha` may
  depend on a layer-1 capability module, which is an architecture question rather than a
  refactor.
- `plan_capability` forwards six arguments to two functions. That is thin, and it is worth
  it only because it makes "a plan is always evidence, then evaluation, then `make_plan`" a
  single enforced path rather than a convention four files re-implement.

## Validation

- `uv run ruff check .` and `uv run ruff format --check .` — clean.
- `uv run pytest` — `132 passed, 1 failed`. The four new tests are the increase over the
  128-test baseline; the failure is the pre-existing Windows `cp949` console-codec error in
  `tests/acceptance/test_p0_p1_agent_journey.py`.
- **No existing test was edited.** Four capabilities changed how they build evidence and the
  suite did not move, which is the evidence that the loop was the only thing extracted.
- Each new test mutation-checked:
  - making `gather_evidence` iterate `alternatives[:1]` fails the labelling test and the
    alternative-selection test;
  - turning a declined (`None`) answer into a fabricated `Finding(False, "declined")` fails
    the decline test.

  The first is the one worth having. A protocol that only asked about the first alternative
  would still pass every real capability, because three of the four declare exactly one
  alternative per requirement — the fallback path only exists in the test fixture, and only
  that test would notice it being dropped.
