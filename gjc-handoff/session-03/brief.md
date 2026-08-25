Resume the vqapr Agent-First Python API migration. This continues gjc session
01a031f9-aa43-703c-b219-d0e2d7a27a4d, whose state is preserved in this repo at
`gjc-handoff/session-state/` and in the sibling repo at `../qlibx/gjc-handoff/`.

## Repositories

- `../qlibx` — branch `jaepil-develop`, package `vqapr` version `0.1.0a16`. The framework itself.
  Most implementation work happens here.
- `vqapr-testbed-2/` (this repo) — the consumer. Kimchi FF5+MOM factor construction.
  Depends on qlibx as an editable sibling via `[tool.uv.sources] vqapr = { path = "../../qlibx" }`.

## The plan under re-review

`gjc-handoff/session-state/plans/ralplan/01a031f9-aa43-703c-b219-d0e2d7a27a4d/pending-approval.md`
is a 963-line consensus plan that is still PENDING APPROVAL. It authorizes no source mutation.
It was authored and reviewed end to end by `gpt-5.6-sol`, not by the model the owner had selected;
the owner's intended `claude-opus-5` profile never applied because unattended ultragoal execution
never produced a user turn boundary. The plan has therefore never been reviewed by the intended model.
Re-reviewing it is the first goal and gates everything after it.

## Verified state as of this session (not inherited claims)

- `../qlibx`: 846 tests pass, ruff clean, `uv run --no-sync pytest -q` in 64.51s.
- `../qlibx/src/vqapr/_internal/models/agent_first.py` exists, is 422 lines, imports cleanly,
  and passes ruff — but NOTHING imports it and NO test covers it. It is orphaned dead code.
  The 846 green tests say nothing about its correctness.
- That file imports `ModelMemory` / `normalize_memory` from `vqapr.models.memory`, a route the plan
  requires to move under `_internal`, and uses `ModelMemory` as the type of `next_state`.
  Whether that is consistent with the plan's `StrategyResult.next_state` contract is unresolved.
- `../qlibx/src/vqapr/public.py` still exists (15004 bytes). Hard removal is planned for T4.
- `vqapr-testbed-2/baselines/` DOES NOT EXIST on this machine. It is gitignored, so the T0 canonical
  baseline captured on the other machine was never transferred. The capture/compare/benchmark
  harness itself IS committed and present.
- Prior session's G001 was checkpointed "complete" on the strength of a test run that predated the
  tree state it claimed to verify.

## Standing constraints

- Do NOT run `git add`, `git commit`, `git push`, tag, or publish. Stop for owner review.
  This is required by both `AGENTS.md` and the plan's own approval state.
- Never checkpoint a goal on evidence older than the current working tree. Re-run the check.
- Before judging that a delegated worker made no progress, re-check the filesystem. The prior
  session cancelled a worker that had already saved its output three minutes earlier.
- Keep delegated slices small and file-scoped. Large slices caused repeated worker stalls.
- Preserve every locked intent ID from the plan: `artifact:api-spec`, `surface:project-workflow`,
  `surface:model-authoring`, `integration:runtime-internals`, `constraint:agent-first`,
  `constraint:economic-explicitness`, `constraint:hard-removal`.
- Scientific parity is the non-negotiable outcome: SMB .971509, HML .972553, RMW .941883,
  CMA .917683, MOM .984659; HML exactly 2,096 callbacks / 97 formations / 110,919 rows.

@goal: Re-review the pending plan against verified repo state
Read the full 963-line pending-approval plan and judge it independently rather than inheriting its
conclusions. Verify its factual claims against both repositories instead of trusting them: confirm
the stated current version, the modules it says exist or must be deleted, the testbed imports it
says must change, and whether its performance thresholds and deletion targets are grounded.
Assess at minimum: whether the T0 baseline premise still holds now that `baselines/` is absent on
this machine; whether recomputing a SHA-256 fingerprint of module bytes plus constructing a fresh
model instance before every callback is viable against the plan's own median 1.10x / p95 1.25x
budget at HML's 2,096 callbacks; whether goal granularity is realistic given that the prior session
stalled repeatedly on oversized slices and tried to split its own G002; whether deleting
`measure_session_effect.py` on the claim its premise is obsolete is actually justified; and whether
the plan's cross-repo release pairing and annotation-closure test are sound. Produce an explicit
verdict per finding: accept as-is, revise, or reject. Record the verdict and its evidence in the
ledger. If the plan needs structural repair beyond localized revision, escalate to ralplan rather
than patching it inline. Do not mutate product source in this goal.

@goal: Re-establish the T0 canonical baseline on this machine
The committed harness (`capture_agent_first_baseline.py`, `compare_agent_first_baseline.py`,
`benchmark_agent_first_shape.py`, `_agent_first_baseline.py`) exists but its captured output does
not. Every downstream parity proof in the plan depends on a T0 baseline that is currently absent
here, so re-capture it before any behavioral change. Run the capture, prove byte and semantic
self-comparison, re-record the five-process same-shape performance baseline after one discarded
warmup, and confirm the external factor correlations and exact HML counts. Confirm the harness
still runs against the current tree rather than assuming the other machine's result transfers.
Record the manifest facts (qlibx SHA, testbed SHA, vqapr version, lock hashes, source digests) in
the ledger so later parity claims are anchored to something real on this machine.

@goal: Resolve the orphaned model runtime adapter and close the authoring boundary
`_internal/models/agent_first.py` is the prior session's unfinished work: 422 lines, zero imports,
zero tests, saved by a worker immediately before cancellation. Decide on evidence whether it is
salvageable or should be rewritten, rather than assuming either. Verify its fresh-invocation,
named-alias-read, and state/diagnostic prepared-root behavior actually matches the `StrategyCall`,
`StrategyResult`, `Hold`/`Rebalance` contracts in the approved plan, and resolve whether its
dependence on `vqapr.models.memory.ModelMemory` for `next_state` is consistent with the planned
contract or a leftover from the old surface. Write the missing tests, wire it into the runtime so
it is genuinely reachable, and prove replay/state/evidence parity. Keep the full qlibx suite green
and ruff clean. This goal closes the prior session's deliberately un-checkpointed G002.

@goal: Implement Project transactions and atomic publication
Implement non-mutating `open`, closed ProjectDeclaration registration, candidate-catalog
validation/preflight with generation-CAS commit, Project materialize/run, one callback root for
decision/state/diagnostics/evidence, content-addressed allocation/record staging with a single
catalog visibility swap, orphan recovery, and CompletedRun atomic Publication. Prove the
transactional claims adversarially, not just on the happy path: two-process writer contention,
preflight failure after multiple staged declarations, and subprocess hard-kill both before and
after the root swap. Run focused integration tests.

@goal: Dogfood and hard-remove the old qlibx API
Migrate shipped venues, constraints, CLI, scaffolds, skills, docs, README, and every showcase and
test onto the capability namespaces and Project workflow. Delete `vqapr.public` and the former
qualified lifecycle/storage/Flow/evidence routes outright, with no redirects, aliases, or
compatibility shims. Prove the exact export surface and prove the removed imports actually fail in
a clean process. Keep qlibx tests, ruff, build, the isolated wheel, and showcases green.

@goal: Migrate the factor testbed and prove scientific parity
Migrate the whole `vqapr-testbed-2` pipeline: `register.py`, models, materialization, simulation,
and atomic publication. Retire or replace the `measure_session_effect.py` diagnostics per the
verdict reached in the re-review goal. Use only supported namespaces, with one root, one run, and
one publish per factor, while retaining every explicit economic declaration. Run the complete factor
rebuild and comparison, and prove exact normalized manifest/trace/row parity plus the performance
thresholds against the baseline re-established earlier in this run. Update the PRD, architecture,
implementation, and handoff records. Do not git add, commit, push, or publish; stop for owner
review after the full cohort and terminal critic gates.
