# Consensus review evidence - vqapr agent layer, 2026-08-23

Six review artifacts from the ralplan consensus run, concatenated so the reasoning behind all 36 findings survives outside `.gjc/`, which is gitignored and does not travel between machines.

Run: session/run id `01a0271d-70c6-7000-bdee-8573530e757e`, repo head `2918fb9`, branch `jaepil-develop`.


---

# [stage-01-architect]

# Architect Review — RALPLAN Stage 1, vqapr framework-agent bridge (pass 1)

Reviewed: `stage-01-planner.md` (sha256 `203ba69643c47078faa1a6fc09e8bbeff17c97d99243b6a39b28cea6dfdd9265`) against `specs/deep-interview-vqapr-agent-layer.md` and the source at `C:/Users/chlje/DevProjects/qlibx/src/vqapr/` (branch `jaepil-develop`, head `2918fb9`). Read-only; no tests, builds, linters, or formatters were run.

## Summary

The plan is unusually well-grounded — its pre-mortems are real, its lane decomposition is sound, and Option A (registry-first) is the correct execution shape for the reason it gives. But three load-bearing claims do not survive contact with the source: `collector()` is **not** the enforcement point the plan treats it as (it sits on ~6 of 25+ stage-producing paths, and every stage the Build Gate actually exercises bypasses it); `publish` has no stated source for the `RunRecordSpec` it structurally requires; and the rung-3 byte-identity criterion is **unreachable** in one project root because the shared publication authority refuses to overwrite an existing output. Separately, the largest "open design question" in the plan (R2, `run_id` derivation) is already answered by existing code — `FrozenRun.identity` is a sha256 content hash already stamped into every recorder row as `run_id`. Status is `BLOCK` on those three, all of which are cheap to fix at plan time and expensive to discover at S9/S14.

## Claims

Claims verified against source, with what held and what did not.

| # | Plan claim | Verdict | Evidence |
|---|---|---|---|
| 1 | `collector()` is the single registry enforcement point (Principle 2, S4) | **Partly false as coverage** | `collector(` appears at only `data/datasets.py:86,117,171`, `exchange/execution_table.py:129,164`, `testing/conformance/runner.py:157`. Everything else constructs `VqaprError` directly. |
| 2 | 10 inline stage literals in `scan.py` + `preflight.py` | **True** | `scan.py:146,279,308,343,394,487,693`; `preflight.py:188,215,278,304` (3 distinct values). |
| 3 | `cli/run.py:177-181` returns no `run_id` | **True** | Returns `occurrences` + `account_version` only (`cli/run.py:170-181`). |
| 4 | `run` persists nothing today | **True** | No `write_text`/`mkdir`/`pq.write_table`/`os.replace` in `flow/simulation.py` or `flow/preflight.py`. |
| 5 | `_instruments`/`_evaluation_times` have no membership check | **True** | `flow/materialize.py:205-252`; only total mismatch trips `materialize.output.empty` at 893-900. |
| 6 | `run_id` derivation is an open question (R2) | **False — already settled in code** | `FrozenRun.identity` is `sha256` over all frozen declarations (`flow/run.py:28-29`, `identity` property ~370); stamped as `run_id` on every recorder row (`flow/simulation.py:1513-1517`, `evidence/recorder.py:31-80`). |
| 7 | `agent/` holds only an empty `__init__.py` + two READMEs | **False** | `agent/sample/` contains `build.py`, `journey.py`, `exchange.py`, `reversal_5d.py`. |
| 8 | `workspace.py:1014-1036` is the atomic-write convention | **True but incomplete** | That range is temp-write → fsync → `os.replace` with retry. The *lock* protocol (`WORKSPACE_LOCK_FILENAME`, `O_CREAT\|O_EXCL`, timeout, stale reclaim) is separate, at `workspace.py:47-64,823-871`. |
| 9 | `new.py` writes two files, takes `kind ∈ {datamodel,strategy}`, requires `--dataset` (R4) | **True** | `cli/new.py:48-84`. |
| 10 | Build Gate has 17 items (P5, R7) | **False** | The spec lists 16: items 1–14 plus 12b and 12c. |

## Analysis

### Stage 1 — Spec compliance

The plan covers the spec's settled decisions faithfully and does not relitigate them. Verb set (7), narrow persistence, `collector()`-only validation, adapter-plus-single-source skill layout, manifest with source sha, the four canon edits, and the five pre-spawn tasks all map to steps. Two spec-mandated outcomes have **no step that produces them** — see Missed Scope (ARCH-03, ARCH-05).

### Stage 2 — Architecture

**Registry-first is the right call, but for a weaker reason than the plan gives.** The plan justifies Option A by depth-of-dependency: the registry touches `collector()`, which "every failure path flows through." That premise is false. Measured: `collector()` has six callsites in three files (`data/datasets.py`, `exchange/execution_table.py`, `testing/conformance/runner.py`). Every other failure-producing path builds `VqaprError` directly — `data/scan.py` (7 sites), `flow/preflight.py` (4), `flow/materialize.py` via `_error` (`materialize.py:187-194`), `workspace.py` via `_workspace_error` (`workspace.py:1733-1739`), `data/windows.py`, `data/resolution.py`, `extension/loading.py`, `extension/registration.py`.

This inverts the sequencing argument in a way that *strengthens* the conclusion. The registry is **not** high-blast-radius — it is a declaration plus a check on a narrow path, and the "37 `Failure.bounded()` callsites / 11 files / ~60 exact-code assertions" risk the plan front-loads is largely notional, because S4 touches none of them. What is genuinely deep is **S1 (the literal lift) + S3 (the declaration)**, which are mechanical. So registry-first is correct, but its real merit is that `descriptors.STAGES` must exist before `materialize`/`publish` mint new stage strings — a *declaration ordering* argument, not a blast-radius one. The plan should keep the order and fix the rationale, because the false rationale leads directly to over-trusting `collector()` as a gate (ARCH-01).

Against the friction fixes and `skill install`: the plan is right that these touch almost nothing shared (`cli/list_.py:74`, `cli/main.py:52-53`, new files under `agent/`), and right to run them as a parallel lane. No objection.

**Where the sequencing is genuinely wrong:** S6 is scheduled as "dep: S4 for the stage, otherwise parallel," but S6 as specified cannot be implemented at the location it names. `materialize()` calls `_evaluation_times(...)` and `_instruments(...)` at `flow/materialize.py:835-836`, **before** `Workspace.open(project_root)` at 837. Both are pure sequence validators; neither receives `project_root`, a `Workspace`, or `spec.dataset_id`, so neither can consult `Workspace.instruments()` (302-315) or `Workspace.evaluation_times()` (317-338). The check has to be a third call sited after the workspace opens. This is a small fix but it invalidates S6's "Files:" line as written.

### Stage 3 — Constructive synthesis

See `## Synthesis` for concrete replacements for S6, S7, S8, and S9.

### Stage 4 — Quality / correctness

**The `unhandled` reintroduction.** The spec's decision — validate in `collector()`, never in `Failure.__post_init__` — is settled and correct in intent. But the plan's S4 says `collector()` "validates ... raising on an unregistered stage" without saying *what* it raises. If it raises `ValueError`, the outcome is exactly the defect the decision was meant to prevent, only relocated: `cli/main.py:67-70` catches `Exception` and routes it to `envelope.failure`, producing `stage:"unhandled"` plus a traceback. And this is reachable from user input, not just from developer error, because `stage` is a runtime parameter at `workspace.py:776,802,810,878`, `flow/materialize.py:180`, and `exchange/execution_table.py:84`. Moving validation out of `__post_init__` changed *when* the typed failure is destroyed, not *whether*. The fix is one line of design: `collector()` must raise a `VqaprError` on a registered meta-stage, so even registry violation stays inside the envelope contract.

**Byte-identity is unreachable as specified.** Rung 3 and Build Gate 14 require the in-process publish and the cold-process publish to be byte-identical. Both go through `_stage_and_publish`, which refuses at `flow/materialize.py:466-474` when `output_path.exists() or lineage_path.exists()`, and then calls `workspace.register_dataset(...)` at 532. So the second publish in the same project root **cannot succeed** — it fails `materialize.publish.path_exists`. Changing `dataset_id` to dodge the collision does not work either: `dataset_id` and `source_id` are embedded in the lineage JSON (`_lineage_envelope`), so two different ids produce two different lineage files by construction. The only shape that satisfies the criterion is two *separate project roots* publishing the same `dataset_id` from the same persisted run. S14 does not say this, and an implementer following S14 literally will produce a test that cannot pass.

**Root-cause vs workaround.** The plan is disciplined here and I found no swallowed-error or silent-default patterns being proposed. S5's "guard the `Workspace.open` call rather than catching broadly" is explicitly the right instinct. C2 correctly identifies that renaming the verb without fixing the README prose reproduces F-001 verbatim — that is genuine root-cause reasoning. Credit where due.

## Root Cause

One root cause explains ARCH-01, ARCH-02, and the plan's overconfidence in Build Gates 6/7: **the plan inherited the spec's phrase "enforced at `collector()` entry" as a statement about coverage, when the source makes it a statement about one narrow path.** The spec chose `collector()` as the *safe* place to validate (correct — it is outside `Failure` construction). The plan read that as the *complete* place to validate. Everything downstream follows: Build Gate 6/7 are treated as assertable by S4 alone; the registry's risk is overestimated (driving the Option A rationale); and no step supplies the static check that would actually give the registry its coverage.

## Findings

| findingId | targetId | action | severity | finding | evidence |
|---|---|---|---|---|---|
| ARCH-01 | S4 | change | P1 | `collector()` enforcement cannot deliver Build Gate 6/7. It sits on ~6 of 25+ stage-producing paths; every stage the Build Gate exercises (`workspace.open.missing`, `preflight.*`, `materialize.*`) bypasses it. Add a static exhaustiveness test as the real coverage mechanism; keep the runtime check as a supplement. | `domain/errors.py:178-179`; `collector(` only at `data/datasets.py:86,117,171`, `exchange/execution_table.py:129,164`, `testing/conformance/runner.py:157` |
| ARCH-02 | S4 | change | P1 | S4 does not state what `collector()` raises. A bare `ValueError` is caught by `except Exception` and becomes `stage:"unhandled"` — the exact defect that moving validation out of `Failure.__post_init__` was meant to prevent. Reachable from user input via runtime `stage` parameters. Must raise `VqaprError` on a registered meta-stage. | `cli/main.py:67-70`; runtime `stage` at `workspace.py:776,802,810,878`, `flow/materialize.py:180`, `exchange/execution_table.py:84` |
| ARCH-03 | S9 | add | P1 | `publish` has no stated source for `RunRecordSpec`. `publish_run_record` requires `dataset_id`, `table_id`, and `value_fields`, and `RunRecordSpec.of` additionally *requires* all five `FLOW_ENVELOPE_FIELDS`. A bare `vqapr publish <run_id>` cannot construct it. | `flow/materialize.py:94-140` (`RunRecordSpec`), `717-743` (`publish_run_record`); `evidence/tables.py:8` |
| ARCH-04 | S7 | change | P1 | R2 treats `run_id` derivation as the largest open design gap, but it is already settled in code: `FrozenRun.identity` is a sha256 over every frozen declaration and is already stamped as the `run_id` column on every recorder row. Minting a second id would give one run two identities and break `publish_run_record`'s `run_identity` provenance. | `flow/run.py:28-29`, `identity` property; `flow/simulation.py:1513-1517`; `evidence/recorder.py:31-80`; consumed at `flow/materialize.py:805` |
| ARCH-05 | S14 | change | P1 | The byte-identity assertion is unreachable as written. The second publish in one project root fails `materialize.publish.path_exists`; changing `dataset_id` to avoid it changes the lineage bytes. The test must publish the same `dataset_id` from the same persisted run into two separate project roots. | `flow/materialize.py:466-474`, `532`; `_lineage_envelope` embeds `dataset_id`/`source_id` |
| ARCH-06 | S6 | change | P2 | The membership check cannot live where S6 puts it. `_evaluation_times`/`_instruments` run at lines 835-836, *before* `Workspace.open` at 837, and receive no `project_root`, `Workspace`, or `dataset_id`. It must be a third call after the workspace opens, still before component invocation. | `flow/materialize.py:835-837`, `205-252` |
| ARCH-07 | S8 | add | P2 | `run` becoming mutating is a change in kind, not degree — it writes nothing today. The plan cites only the atomic-write half of the convention and omits the lock protocol, plus cleanup and growth bounds. Directory creation needs its own refuse-on-existing + atomic-rename story. | no writes in `flow/simulation.py`/`flow/preflight.py`; lock at `workspace.py:47-64,823-871`; write/swap at `workspace.py:1014-1036` |
| ARCH-08 | S8 | add | P2 | `run_id` is emitted once and is then undiscoverable. `list` has no `runs` kind, so an agent that loses the envelope cannot recover the id — and Build Gate 14 requires using it in a *new shell*. Add `runs` to `KINDS`/`_ACCESSORS`. | `cli/list_.py:16-35`; Build Gate 14 |
| ARCH-09 | S11 | change | P2 | The plan's `agent/` inventory is wrong: `agent/sample/` already holds four modules, and `journey.py` imports `vqapr.extension.fingerprint` — a framework internal — which already violates Principle 6. No step reconciles this and no boundary test guards it. | `agent/sample/{build,journey,exchange,reversal_5d}.py`; `journey.py:15-17`; no `agent` match in `tests/boundaries/` |
| ARCH-10 | C3 | add | P2 | Canon drift is wider than C3's single §10.4 edit. The architecture layout tree places `descriptors.py` *inside* `agent/` and names `onboarding.py` with preview/apply/update/remove; §13 step 2 repeats `agent/descriptors`; PRD §11.3 still describes the old verb set. The plan correctly puts descriptors at top level (Principle 6 forbids `domain/` importing `agent/`) but never updates the docs that say otherwise. | `docs/vqapr-architecture.md:2752-2757`, §13 step 2, §10.4; `docs/vqapr-prd.md` §11.3 |
| ARCH-11 | S9 | add | P2 | R1 correctly identifies the unbounded-scan hazard on 4,962 names but explicitly declines to fix it ("flagging, not fixing"), while making S9's shape depend on the answer. A plan that defers its own highest-practical-risk schema decision to implementation time will have it guessed. Fix the schema in the plan. | plan R1; `workspace.py:302-315`, `317-338` |
| ARCH-12 | S3 | change | P2 | `stage` names two disjoint closed vocabularies. `descriptors.STAGES` will hold failure/CLI stages (`materialize.input`, `workspace.list`); the recorder's `stage` column holds `OperationRole` (`STRATEGY_CALLBACK`/`VALUATION`/`MONITORING`). `VALUATION` exists in both `FailureFamily` and `OperationRole` with different meanings. An agent reading the rendered `references/stages.md` will conflate them. | `evidence/tables.py:8`; `flow/simulation.py:1516`; `runtime/agendas.py:26-29`; `domain/errors.py:19-28` |
| ARCH-13 | S10 | add | P3 | Friction fix (b) covers only the missing input file. `cli/new.py` raises a bare `FileExistsError` on re-run, and `cli/run.py` raises bare `TypeError`/`ValueError` for a non-mapping or incomplete spec — all become `unhandled`. Rung 2 uses `new`, and the Spawn Gate allows 3 tries per rung, so a retry hits this. | `cli/new.py:69-71`; `cli/run.py:171-174` |
| ARCH-14 | P5 | change | P3 | The Build Gate has 16 items (1–14 plus 12b, 12c), not 17. P5's "17/17" observable and R7's "17 items" are both off by one, so the gate's own pass condition is unstated. | spec Build Gate list |
| ARCH-15 | S11 | change | P3 | R3 and Pre-Mortem 3 both cite "step S17" as a mitigation. There is no S17 — the work breakdown ends at S14, and MISSION-A.md is P3. A dangling dependency in the plan's most evidentially thin risk. | plan R3, Pre-Mortem 3, Work Breakdown |

## Synthesis

Concrete structure for the four thinnest places, so these are decisions rather than deferrals.

### S7 — the `.vqapr/runs/<id>/` contract (replaces the open half of R2)

**`run_id` is `FrozenRun.identity`.** Do not mint one. It is already a sha256 over every frozen declaration (`flow/run.py:28-29`) and is already the `run_id` column on every recorder row (`flow/simulation.py:1513-1517`). This closes R2(a) outright: the id is content-addressed and reproducible, and R2's stated worry — "two identical runs collide" — is not a collision but the correct answer, since identical frozen declarations *are* the same run. Refuse-on-existing is then consistent with `_stage_and_publish` (`materialize.py:466-474`) rather than a new convention.

**Layout.**

```
.vqapr/runs/<run_id>/
  manifest.json          schema_version, run_id, package_version, created_at,
                         finalization{...}, tables[{table_id, row_count, sha256}]
  tables/<safe_table_id>.parquet    one file per recorder table
  publish-spec.yaml      ready-to-run publish input (see S9)
```

**Encoding: parquet, not JSON.** This closes R2(b) and retires Pre-Mortem 2 structurally. Build each table with `pa.Table.from_pylist` and `pq.write_table(..., compression="zstd")` — the same path `materialize.py:505-513` already uses — so `Decimal` and tz-aware `datetime` survive as Arrow types. JSON would degrade `event_time` to a string, and `publish_run_record` maps `event_time` straight onto `available_at` (`materialize.py:774-777`), which the shared authority then re-validates as a timestamp at `materialize.py:527-529`. So a JSON round trip does not merely change bytes — it makes cold publish *fail validation*. That is a sharper and more testable failure than "bytes differ."

**Durability.** Stage into `.vqapr/runs/.<run_id>.tmp-<pid>/`, fsync each file, then `os.replace` the directory into place, reusing the `WORKSPACE_SWAP_ATTEMPTS`/`WORKSPACE_SWAP_BACKOFF` retry loop (`workspace.py:1028-1036`) for the Windows case. No workspace lock is needed — the path is unique per run and never read-modify-written — but the refusal on an existing directory must be a typed failure, not an `OSError`.

**Growth/cleanup.** Out of scope for this cycle, but `manifest.json` must carry `created_at` so a later sweeper has a key. State that explicitly rather than leaving it unsaid.

### S8 — surfacing `run_id`

`cli/run.py:177-181` becomes `success("run.complete", run_id=frozen.identity, occurrences=..., account_version=...)`. `frozen` is already in scope at `cli/run.py:176`. This is the only change Build Gate 13's `run_id` requirement needs.

### S9 — `publish` input (closes ARCH-03 and the Build Gate 14 shape conflict)

The spec fixes publish's input as a YAML spec; Build Gate 14 writes `vqapr publish <run_id>`. Both are satisfiable if **`run` writes the publish spec at persist time**. Every field except `dataset_id` is derivable: `table_id` and the declared value fields come from `AcceptedRunState.recorder_manifests`, and the five envelope fields are mandatory anyway.

```yaml
# .vqapr/runs/<run_id>/publish-spec.yaml, written by `run`
run_id: <frozen identity>
table_id: vqapr.fill
dataset_id: <REQUIRED — the one thing the user must choose>
value_fields: [run_id, producer_id, stage, event_time, sequence, <measures...>]
```

`vqapr publish <run_id>` then means "use the spec this run already wrote," with `--spec PATH` to override. Build Gate 14 becomes literally true, the agent gets a discoverable artifact instead of a schema to guess, and `constraint:skill-never-bypasses` holds because nothing is inferred — `dataset_id` still fails typed when absent.

### S6 — materialize input schema (closes R1 and ARCH-06)

Require explicit bounds; no implicit "all".

```yaml
component_id: <id>
dataset_id: <output id>
value_fields: [...]
instruments:
  from_dataset: <source dataset_id>     # the only sanctioned whole-universe form
  # or: explicit: [A, B, C]
evaluation_times:
  from_dataset: <source dataset_id>
  start: 2020-01-01T00:00:00+09:00      # both required with from_dataset
  end:   2020-12-31T00:00:00+09:00
  # or: explicit: [...]
```

A bare `from_dataset` without `start`/`end` is refused at the input stage — this is what prevents the 4,962 × ~11-year cross product while still letting an agent express "the whole universe for this quarter" without transcribing 4,962 tickers (which is Pre-Mortem 1's actual failure mode: hand-typed lists drift).

**Placement.** Add a third call after `Workspace.open`, not inside the two pure validators:

```python
times = _evaluation_times(evaluation_times)          # 835, unchanged
selected_instruments = _instruments(instruments)     # 836, unchanged
workspace = Workspace.open(project_root)             # 837
_require_membership(workspace, spec.dataset_id, times, selected_instruments)  # new
```

It must raise `_INPUT_STAGE` with unknown identities in bounded `examples`, and must run before `workspace.component(...)` so nothing is published.

### ARCH-01 — what actually gives the registry coverage

Keep `collector()` validation (the spec settled it; it is the right runtime guard). Add the mechanism that supplies coverage: a test that imports every module under `src/vqapr/`, collects every module-level `*_STAGE` constant plus the inline values S1 lifts, and asserts each is declared in `descriptors.STAGES`. That is a static, total check, and it is what makes Build Gate 6/7 honest. Pair it with `descriptors.FAILURE_STAGES ⊂ STAGES`, where `collector()` checks the subset and `STAGES` is the flat union that Build Gate 7's `workspace.list ∈ STAGES` needs.

## Recommendations

Ordered by cost of discovering them late.

1. **Fix S4's mechanism (ARCH-01, ARCH-02).** Add the static exhaustiveness test; specify that `collector()` raises `VqaprError` on a registered meta-stage. Both are plan-time edits; both are load-bearing for Build Gates 6 and 7.
2. **Close S9's `RunRecordSpec` gap (ARCH-03)** using the run-written `publish-spec.yaml` above. Without this, S9 is not implementable.
3. **Replace R2 with the settled answer (ARCH-04).** `run_id = FrozenRun.identity`. This removes the plan's self-described "largest single design gap" at zero cost and prevents a second identity for one run.
4. **Rewrite S14's assertion (ARCH-05)** to two project roots, same `dataset_id`, same persisted run. Add the stronger sub-assertion that the cold-process `available_at` column reads back as a timestamp, not a string.
5. **Relocate S6's check (ARCH-06)** to a post-`Workspace.open` call and fix the schema (ARCH-11) before S9 starts, as the plan itself recommends.
6. **Extend S8** with the runs-directory refuse-on-existing/atomic-rename story and `created_at` (ARCH-07), and add `runs` to `list` (ARCH-08).
7. **Reconcile the `agent/` inventory (ARCH-09)** — either bring `agent/sample/` under Principle 6 or state explicitly that it is exempt, and add the boundary test that does not currently exist.
8. **Widen C3 (ARCH-10)** to the architecture layout tree, §13 step 2, and PRD §11.3.
9. **Housekeeping:** disambiguate `stage` in the rendered catalog (ARCH-12); extend fix (b) to `new.py` and the spec-shape raises (ARCH-13); correct 17→16 (ARCH-14); repoint S17 to P3 (ARCH-15).

## Tradeoffs

| Tension | What the plan does | Assessment |
|---|---|---|
| Registry at `collector()` vs. coverage | Treats `collector()` as universal | Papers over. The spec's *placement* choice is right; the plan's *coverage* inference is not. Resolved by adding a static check, not by moving validation. |
| Registry raise vs. typed envelope | Silent on what is raised | Papers over. A `ValueError` re-creates `unhandled` one layer out. Cheap fix: typed raise on a meta-stage. |
| Failure-only registry vs. agent-observable stages | R5/S3 keep three buckets; `STAGES` spans all | **Resolved, and correctly.** R5 is one of the plan's best sections. Only refinement: `STAGES` must be the flat union (Build Gate 7 does membership on it), with `FAILURE_STAGES` the subset `collector()` checks. |
| Content-hash vs. uuid `run_id` | Left open in R2 | Papers over a question the code already answers. `FrozenRun.identity` is the content hash and is already in every row. |
| `.vqapr/runs/` durability | Cites the atomic-write half | Partly papers over. Directory creation ≠ file replace; lock protocol, cleanup, and growth are unaddressed. Concurrency is genuinely benign (unique path, no read-modify-write) — but say so rather than omit it. |
| Bounded selection vs. agent ergonomics | R1 flags, declines to fix | Papers over, and the plan admits it. An explicit-only list is safe but invites the hand-transcription that *is* Pre-Mortem 1. `from_dataset` + mandatory date range is the shape that is both bounded and typo-proof. |
| JSON vs. parquet row encoding | R2 leans parquet, S7 defers | Correct instinct, insufficiently forced. JSON does not merely change bytes — it makes cold publish fail schema validation. That makes parquet mandatory, not preferable. |

## Architectural Status

BLOCK

## Code Review Recommendation

REQUEST CHANGES


---

# [stage-01-critic]

# RALPLAN Stage 1 — Critic Review (pass 1, plan-only lane)

Plan under review: `stage-01-planner.md` (sha256 `203ba69643c47078faa1a6fc09e8bbeff17c97d99243b6a39b28cea6dfdd9265`).
Spec: `deep-interview-vqapr-agent-layer.md`. Repo `C:/Users/chlje/DevProjects/qlibx`, branch `jaepil-develop`.
Architect output NOT consumed this pass, per lane assignment.

## Verdict

**ITERATE**

The plan is well-sequenced, evidence-dense, and faithful to the spec's settled decisions. Option A is correctly selected and the two rejected options are genuinely invalidated rather than strawmanned. It does not need a rewrite. It does need four P1 corrections, all of which are places where the plan (and in two cases the spec's own Technical Context) asserts a fact about the repository that the repository contradicts, and where an implementation agent following the plan literally would produce a broken or unexecutable result.

---

## Principle-Option Consistency

Principles 1-5 genuinely select Option A. The chain is sound: Principle 2 (validation at `collector()` only) plus Driver D1 (10 inline literals block the registry) makes the registry the deepest dependency, and registry-first is the only order in which the two new verbs are born inside the registry rather than retrofitted. Option B's rejection is well-argued and non-rhetorical — the attribution-destruction argument (first full-registry run fails across new and old code simultaneously) is a real cost, not a manufactured one. Option C's rejection is likewise concrete: fix (d) genuinely is only half-completable before `materialize` exists. Notably, the plan absorbs Option B's insight rather than discarding it (S7 designed in parallel), which is the correct treatment of a rejected-but-informative alternative.

**Principle 6 is violated — not by the recommended option, but by the repository as it already stands.**

Principle 6 states: "`src/vqapr/agent/` may be imported by the `skill` CLI verb and nothing else; nothing in `agent/` may import framework internals beyond `vqapr.descriptors` and package metadata."

This is false today, and the plan has no step that reconciles it. `git ls-files src/vqapr/agent/` returns seven tracked files, not the "empty `__init__.py` + two README stubs" that the spec's Technical Context and this plan both assume:

```
src/vqapr/agent/__init__.py
src/vqapr/agent/sample/README.md
src/vqapr/agent/sample/build.py
src/vqapr/agent/sample/exchange.py
src/vqapr/agent/sample/journey.py
src/vqapr/agent/sample/reversal_5d.py
src/vqapr/agent/skill/README.md
```

And those modules import framework internals directly:
- `src/vqapr/agent/sample/journey.py:15-17` — `from vqapr.agent.sample.build import ...`, `from vqapr.extension.fingerprint import fingerprint_component`, `from vqapr.public import (...)`
- `src/vqapr/agent/sample/exchange.py:13` — `from vqapr.public import AcademicExchange, ListingAccess, TradeRule`
- `src/vqapr/agent/sample/reversal_5d.py:15` — `from vqapr.public import (...)`

There is also a live test that imports them: `tests/agent/test_sample_panel.py:16-23` imports `vqapr.agent.sample.build` and `vqapr.agent.sample.reversal_5d`.

This matters concretely. The spec defers `sample-journey` and marks `constraint:no-auto-generate` invalid "because sample-journey is deferred" — but deferral describes future work, whereas this code is already tracked and already tested. An implementation agent that reads Principle 6 as a rule to enforce has two bad options: it either adds a boundary test that immediately fails against `agent/sample/`, or it deletes/moves tracked, tested source that no step authorizes it to touch. Neither is intended. Principle 6 must be restated to scope over the *new* surface only (`agent/skill/`, `agent/targets.py`, `agent/` package init) and to explicitly record `agent/sample/` as pre-existing, out of scope, and deliberately exempt — or, if the intent really is repo-wide enforcement, a step must own that migration and its record.

Secondary consistency note: Principle 4 ("Narrow persistence") and Principle 5 ("Reuse the existing atomic-write convention") are correctly held by S7/S8. Principle 1 (guard-before-open) is correctly propagated to S9 and S10. Principle 3's cycle-break via authority split is the right resolution and C1 lands it in canon.

---

## Acceptance Criteria Traceability

**Item-count discrepancy, resolved first.** The plan's P5 asserts "execute all 17 Build Gate items" and the run context repeats 17. The spec's Build Gate checklist contains **16** checkboxes (1-14 with 12b and 12c inserted), while the spec's own Ontology row for Build Gate says "**14** command-to-observable items." Three different numbers across two documents, and the plan enumerates none of them. P5's observable "17/17" is therefore not checkable against any list that exists. The table below traces the 16 checkboxes that the spec actually presents.

### Build Gate

| # | Gate item (abbrev) | Covering step(s) | Status |
|---|---|---|---|
| 1 | `mkdir t && cd t && vqapr list datasets` -> ok:true, `workspace.list`, count:0, exit 0 | **S5(a)**; test in S13 integration + empty-workspace smoke | Covered. Targets the real defect at `cli/list_.py:74-75` (`Workspace.open` unguarded, verified) |
| 2 | `vqapr --help` lists all 7 verbs w/ one-line each | **S5(c)** (help text) + **S9** (registers `materialize`/`publish` in `_COMMANDS`) + **S12** (registers `skill`) | Covered. `main.py:19-24` has 4 verbs today (verified); `main.py:52` is bare `add_parser(name)` (verified) |
| 3 | Each of 7 verbs `--help` -> non-empty description | **S5(c)**, legitimized by **C1** | Covered |
| 4 | `vqapr new run-spec > spec.yaml` contains 8 `_REQUIRED` keys | **S10(d)** | Covered but **blocked by unresolved R4**. `_REQUIRED` confirmed at `cli/run.py:33`. The stdout-vs-single-JSON-line collision is named as an open question and explicitly deferred ("Recommend resolving before S10") — so the step is not executable as written |
| 5 | `vqapr run nope.yaml` -> ok:false, `stage != "unhandled"`, no `traceback`/`detail` | **S10(b)** | Covered; see CRIT-09 on the suppression claim |
| 6 | Template spec -> ok:false, registered stage, `failures[].code` starts with it | **S10** + **S4** | Covered |
| 7 | `len(vqapr.descriptors.STAGES) >= 1`; `list datasets` stage is a member | **S3** (first half) + **S4** (second half) | Covered. R5's bucket-separation caveat is correctly identified and assigned to S3 |
| 8 | `skill install --target both --dry-run` -> `.git` root printed, exit 0, git status unchanged | **S12** | Covered |
| 9 | Install both -> `.agents/.../SKILL.md` exists; `.claude/...` adapter <=20 lines contains `.agents/skills/vqapr` | **S11** (content) + **S12** (install) | Covered. Plan correctly flags (R3) that this item's passing does not entail its intent |
| 10 | `head -1` is `---`, has `name:`/`description:`, 80-124 lines | **S11** | Covered |
| 11 | `git status --porcelain AGENTS.md CLAUDE.md` empty | **S12** | Covered |
| 12 | `skill list` both installed:true; `remove --target both` -> both false, git clean | **S12** | Covered |
| 12b | Modified SKILL.md not deleted by `remove`, reported; `--force` deletes | **S12** | Covered |
| 12c | Source SKILL.md modified, version unchanged -> `skill list` reports stale | **S12** | Covered. R8 correctly notes detection without remedy |
| 13 | rung 1-3 all ok:true, `run_id` in envelope | **S6** + **S8** + **S9** | Covered |
| 14 | **New shell** `vqapr publish <run_id>` -> ok:true *(dominating)* | **S9** + **S14** | Covered on paper, **unexecutable as written** — see CRIT-02, CRIT-03, CRIT-04 |

**Build Gate items with no covering plan step: 0.** Every checkbox maps to at least one step. The exposure is not absence of coverage but four items (4, 14, and transitively 6 and 13) whose covering steps rest on unresolved or falsified premises.

### Spawn Gate

| Condition | Covering step(s) | Status |
|---|---|---|
| Zero vqapr-attributable `blocked` | S5, S10 (the four measured friction fixes), gated by **P5** | Covered as an outcome of the friction-fix lane |
| At most 2 `slowed` | Same lane; **P5** dry run is the only pre-check | Weakly covered — no step *measures* friction cost pre-spawn; it is asserted by P5 passing |
| Zero `qlibx/src/` reads (or self-recorded) | **S11** (skill sufficiency), **P3** (MISSION-A prohibits + requires self-report) | Covered. R3 correctly identifies this as the residual-risk condition |
| Each rung's first invocation succeeds within 3 tries | **S10(d)** template emitter + **S11** ladder text | Weakly covered — no step targets try-count directly; it is an emergent property of template + skill quality. Acceptable, but should be named as such |
| rung 1: row/date/instrument counts match pre-measured | **P1** | Covered |
| rung 2: (date, instrument) coverage ratio matches pre-declared | **P2** + **S6** | Covered |
| rung 3: in-process vs cold-process publish **byte-identical** | **S14** | Covered on paper, **contradicted by `_stage_and_publish` refuse-on-existing** — see CRIT-03 |
| FRICTION.md has `wrong` severity | **P4** | Covered |

### Pre-spawn tasks (spec: 5 required)

| Task | Step | Status |
|---|---|---|
| Measure/freeze `adjusted_prices.parquet` rows, date range, instruments | **P1** | Covered |
| Compute/freeze rung-2 coverage ratio | **P2** | Covered |
| Lift `scan.py` 7 + `preflight.py` 3 inline literals | **S1** | Covered (count nuance in CRIT-11) |
| Write `MISSION-A.md` | **P3** | Covered |
| Four canon edits **and each one's implementation record** | **C1** (edits i+ii, record 047), **C2** (iii, 048), **C3** (iv, 049) | **Partial** — 4 edits, 3 records. See CRIT-08 |

### Scope creep check (steps satisfying no gate item)

S0, S2, S7, S13 carry no direct gate item, and all four are legitimately justified as preconditions or guard rails; the plan states this honestly rather than inflating their gate coverage. C1/C2/C3 map to pre-spawn task 5. **No scope creep found.** The plan is, if anything, slightly under-scoped: nothing addresses the `agent/sample/` reality (CRIT-01).

---

## Verification Adequacy

### The ~60 exact-error-code assertions

The three-layer defence is structurally right, and layer 3 is the one that actually carries the weight. I verified the mechanism: `collector(stage, family)` at `src/vqapr/domain/errors.py:179-180` merely constructs `_Collector(stage=stage, family=family)`, and `_Collector.done()` passes `self.stage` straight through to `Diagnosis`. Because `code` strings are assembled independently at the 37 `Failure.bounded()` callsites and never pass through `collector()`, a membership check there provably cannot rewrite a code. The plan's claim that "a passing registry cannot alter any emitted `code`" is correct, and it is correct for the reason given.

Layers 1 and 2 are weaker than presented. Layer 1 (S0's `test_known_codes_are_stable`, a hand-transcribed sorted tuple of every asserted code) duplicates assertions that ~60 existing tests already make; if a code drifts, those tests fail anyway. Its marginal value is naming the failure well, at the cost of a manually maintained list that will itself drift. Layer 2 ("for each new constant, a test that the constant equals its historical string") is a tautology test — it asserts a literal equals a literal, and will pass even if every callsite stops using the constant. The real proof is the one the plan already names: `tests/data/test_scan.py` and `tests/flow/test_preflight.py` passing unchanged. Keep that; drop or sharply narrow layers 1-2.

**Verdict: adequate**, mainly on the strength of layer 3 and the unchanged-suite re-run.

### The `materialize` partial-instrument-mismatch case

This is the strongest section of the plan and it is correct on the facts. I verified every load-bearing claim:
- `_instruments` (`flow/materialize.py:230-249`) rejects invalid identities, empty, and duplicates — and performs **no** membership check. Confirmed.
- `_evaluation_times` (`flow/materialize.py:210-227`) has the symmetric blind spot. Confirmed.
- Every `materialize()` callsite in `tests/flow/test_materialize.py` passes `instruments=("A", "B")` — lines 99, 123, 146, 169, 197, 230, 256. Confirmed; the mismatch axis has genuinely never been exercised, and the plan's reasoning that partial overlap is unreachable at arity 2 is right.

The five-test design is well-formed: widening the fixture to >=4 instruments while keeping the two-name tests as an untouched regression baseline is the correct additive shape; asserting **no artifact written** is exactly the right assertion because publishing-and-exiting-0 is the actual bug; and test 5 (total mismatch still yields `materialize.output.empty`) correctly protects the existing code from being shadowed. Placing the check at the input stage before component invocation is right.

One substantive gap: the plan does not note that the membership check's data source, `Workspace.instruments()` (`workspace.py:302-316`), executes a `SELECT DISTINCT ... ORDER BY` full-column scan via `scan.distinct_values`, as does `Workspace.evaluation_times()` (`workspace.py:318-338`). On the 4,962-instrument dataset this adds two full scans to every `materialize` call, on the rung-2 path that the 30-minute Build Gate budget already strains (R7). The check is correct; its cost needs an explicit decision. See CRIT-10.

**Verdict: adequate, with a cost gap.**

### The cold-process `publish` round trip

The plan's instinct is exactly right — it correctly identifies that an in-process persist/reload test is "a false negative by construction" and mandates a genuine subprocess. Pre-Mortem 2 is the sharpest analysis in the document. But the prescribed mechanism does not work, and the criterion it targets is not reachable in the workspace shape the plan assumes.

**The invocation does not exist.** Pre-Mortem 2 and S14 prescribe `subprocess.run([sys.executable, '-m', 'vqapr', ...])`. There is no `src/vqapr/__main__.py` — `find` reports it missing, and `pyproject.toml` declares only a console script, `vqapr = "vqapr.cli:main"` under `[project.scripts]`. `python -m vqapr` therefore fails with `No module named vqapr.__main__`. Either S14 uses the installed `vqapr` console script (with the attendant PATH/venv resolution question in a test, on Windows), or a step must add `__main__.py`. Neither is in the plan. See CRIT-02.

**The byte-identity criterion collides with refuse-on-existing.** `publish_run_record` (`flow/materialize.py:717`) delegates publication to `_stage_and_publish`, which at `flow/materialize.py:464-474` raises `<publish>.path_exists` when **either** `.vqapr/materialized/<stem>.parquet` or `<stem>.lineage.json` already exists:

```
output_path = output_directory / f"{stem}.parquet"
lineage_path = output_directory / f"{stem}.lineage.json"
if output_path.exists() or lineage_path.exists():
    raise _error(_PUBLISH_STAGE, f"{_PUBLISH_STAGE}.path_exists", ...)
```

So "publish in-process, then publish the same run in a cold process, then compare the two artifacts byte-for-byte" cannot happen in one workspace: the second publish fails on `path_exists`, not on any type-fidelity problem. The plan's own R2 cites this same guard as precedent for run_id derivation but never connects it to S14's assertion or to Spawn Gate rung 3. Achieving the criterion requires two identically-seeded project roots (or a declared dataset_id differing per publish, which then changes `stem` and hence the lineage `output.dataset_id` field, defeating byte-identity). This is a design decision S7/S14 must make explicitly. See CRIT-03.

One piece of good news the plan does not claim and should: byte-identity is achievable in principle, because the lineage payload is deterministic. `_lineage_envelope` (`flow/materialize.py:362-386`) emits only `schema_version`, `operation`, `output.{dataset_id,source_id,value_fields}`, and `instruments` — no wall-clock timestamp, no absolute path. A `search` for `now(|utcnow|generated_at|created_at` across `materialize.py` returns no such call. Worth stating in S7, because it is the precondition that makes the whole rung-3 criterion sane, and an implementation agent who assumes otherwise will waste effort building a normalizer.

**Verdict: inadequate as written** — right diagnosis, unexecutable prescription.

---

## Alternatives and Risks

**Alternatives are real, not straw men.** Options B and C are each given a genuine pro that the recommended option lacks (B: earliest attack on the dominating item and maximum settling time for the highest-uncertainty design; C: cheapest visible win, independently shippable). Both rejections turn on specific, checkable mechanisms rather than assertion. Best signal of good faith: the plan *absorbs* B's core insight (S7 as parallel design work) and *salvages* C's independent half (fixes (a)/(c) as a parallel lane) instead of discarding rejected options wholesale. That is the correct handling.

**The risks raised are, with one exception, the ones that will actually bite.** R1 (unbounded universe scan) is well-evidenced and correctly rated highest-practical. R2 (run_id derivation and row encoding) correctly names the largest design gap and correctly ties JSON type degradation to the rung-3 criterion. R4 (stdout vs one-JSON-line envelope) is a genuine contradiction between Build Gate 4 and the envelope contract — I confirmed `emit` at `cli/envelope.py:125-140` writes exactly one `json.dumps` line to stdout, so the collision is real. R5 (success/CLI stages outside the failure registry) is confirmed: `envelope.py:61-62` sets `stage: "cli.usage", family: None` and `:108-109` sets `stage: "unhandled", family: None`. R7 (unmeasured 30-minute budget) is honest and its mitigation is sensible. R3 correctly identifies the one gate item whose passing does not entail its intent, and gives a concrete contingency.

**Risks that should have been raised and were not:**

1. **The `agent/sample/` package already exists and violates Principle 6** (CRIT-01). Highest-severity omission, because both the spec's Technical Context and the plan assert the directory is empty, and a step derived from that false premise breaks a passing test.
2. **`publish` has no runnable module entrypoint** (CRIT-02).
3. **Refuse-on-existing forecloses the rung-3 byte-identity comparison** (CRIT-03).
4. **`publish_run_record`'s call shape is far heavier than "reloads and calls it"** (CRIT-05). Its signature is `publish_run_record(project_root, spec: RunRecordSpec, result: object)`, and at `flow/materialize.py:745` it reaches through `getattr(getattr(result, "final_state", None), "recorder_rows", None)`. A cold process holds no `SimulationResult` — by Principle 4, deliberately — so `publish` must synthesize a carrier object exposing `.final_state.recorder_rows`. Additionally `RunRecordSpec` (`flow/materialize.py:94-139`) requires `dataset_id`, `table_id`, and `value_fields`, and validates that `value_fields` covers the Flow envelope fields; at `:754` the row lookup is `recorded.get(spec.table_id, ())`. So the publish YAML must carry `dataset_id`, `table_id`, and `value_fields`, and none of that schema is specified anywhere in the plan.
5. **Build Gate 5's no-`detail` guarantee is not actually a function of typedness** (CRIT-09). In `envelope.failure` (`cli/envelope.py:96-121`), `detail` is written whenever the traceback exceeds `MAX_INLINE_TRACEBACK_LINES` (8, at `:23`) **and** `project_root` is not None — regardless of whether the error carries `as_dict()`. A typed `VqaprError` raised deep in the stack therefore still gets a `detail` key. The plan's Observability section asserts "`detail` present is a reliable proxy for 'this escaped as an unhandled exception'", which is false as written. S10 must either guarantee the typed guard raises shallowly or suppress `detail`/`traceback` for errors carrying `as_dict()`.

---

## Thinness

Areas where an implementation agent that has not read the source cannot proceed without inventing scope:

**S7 (largest gap; the plan says so itself).** Needs, concretely: (a) the chosen `run_id` derivation with its collision rule stated as a decision, not options; (b) the on-disk encoding of `recorder_rows` — it is `Mapping[str, tuple[Mapping[str, object], ...]]` (`flow/run_state.py:124`), `object`-valued, with `Decimal` and tz-aware `datetime` both live in the codebase (`agent/sample/build.py:18-20` uses `Decimal` and `ZoneInfo`; `PRICE_TYPE = pa.decimal128(18, 4)` at `:26`) — with the exact per-type mapping written out; (c) the manifest field list; (d) the finalization-provenance field list; (e) **the two-workspace or two-root strategy that makes the S14 byte-identity comparison possible at all**; (f) the note that lineage is already timestamp-free and path-free, so byte-identity needs no normalizer.

**S9.** Needs the `materialize` and `publish` YAML schemas as literal key lists. For `publish` at minimum: `run_id`, `dataset_id`, `table_id`, `value_fields` (see CRIT-05). It must also resolve the contradiction between its own text ("both take a YAML spec file exactly as `register`/`run` do") and Build Gate 14's `vqapr publish <run_id>`, which is a positional id, not a spec path — as written these are two different CLI surfaces and the step asserts both (CRIT-04).

**S6.** Needs the exact failure `code` string for the new membership check (e.g. `materialize.input.instruments_unknown`), because S13's test asserts on it and the two must be written against one agreed value. It should also state the `examples` bound and confirm the check reuses `_INPUT_STAGE` (`materialize.input`, per the existing `f"{_INPUT_STAGE}.instruments_invalid"` convention at `flow/materialize.py:234`), and decide the scan-cost question in CRIT-10.

**S3.** Needs the three bucket names as literal identifiers and the rule for which bucket `collector()` validates against, since R5 correctly warns that conflating them lets `collector()` admit `workspace.list` as a failure stage. It should also state whether `vqapr/descriptors.py` is exempt from `public.py`'s `__all__` (105 names, asserted exhaustively at `tests/boundaries/test_public.py:181-322`) — the plan says "possibly `public.py`" and leaves it open, but that test asserts exact tuple equality, so guessing wrong turns it red.

**S12.** Needs the manifest JSON schema written out, and needs to state how `skill install` behaves when `agent/sample/` is present (it must not ship sample sources into the target skill directory).

**S14.** Needs the concrete invocation decision from CRIT-02 and the workspace-shape decision from CRIT-03 before it can be written at all.

**P5.** Needs the enumerated gate list it is asserting `N/N` against (CRIT-06).

---

## Findings

| findingId | targetId | action | severity | evidence |
|---|---|---|---|---|
| CRIT-01 | Principles §6 | change | P1 | `git ls-files src/vqapr/agent/` returns 7 tracked files incl. `sample/{build,exchange,journey,reversal_5d}.py`; `agent/sample/journey.py:15-17` imports `vqapr.extension.fingerprint` + `vqapr.public`; `agent/sample/exchange.py:13` imports `vqapr.public`; `tests/agent/test_sample_panel.py:16-23` imports them. Principle 6 is falsified by tracked, tested source. Scope P6 to the new surface and record `agent/sample/` as an explicit pre-existing exemption, or add a step that owns the migration. |
| CRIT-02 | S14 | add | P1 | Pre-Mortem 2 and S14 prescribe `subprocess.run([sys.executable, '-m', 'vqapr', ...])`, but `src/vqapr/__main__.py` does not exist (`find` reports missing) and `pyproject.toml` `[project.scripts]` declares only `vqapr = "vqapr.cli:main"`. Add `__main__.py` as a step, or change S14 to invoke the console script and state how the test resolves it. |
| CRIT-03 | S14 | change | P1 | `flow/materialize.py:464-474` — `_stage_and_publish` raises `<publish>.path_exists` if the parquet **or** lineage path exists; `publish_run_record` (`:717`) routes through it. In-process publish followed by cold-process publish of the same run collides on `path_exists`, so the rung-3 byte-identity assertion is unreachable in one workspace. Specify the two-root (or equivalent) comparison strategy in S7/S14. |
| CRIT-04 | S9 | change | P1 | S9 states both verbs "take a YAML spec file exactly as `register`/`run` do", but Build Gate 14 is `vqapr publish <run_id>` — a positional id. Spec constraint and Build Gate item disagree; the step asserts both. Pick one surface and state it. |
| CRIT-05 | S9 | add | P2 | `publish_run_record(project_root, spec: RunRecordSpec, result: object)` at `flow/materialize.py:717-720`; reads `getattr(getattr(result,"final_state",None),"recorder_rows",None)` at `:745`; `RunRecordSpec` requires `dataset_id`/`table_id`/`value_fields` (`:94-139`); rows looked up via `recorded.get(spec.table_id, ())` at `:754`. Specify the carrier object and the publish YAML key list. |
| CRIT-06 | P5 | change | P2 | P5 asserts "all 17 Build Gate items" / "17/17"; spec checklist has 16 checkboxes (1-14 + 12b + 12c); spec Ontology row says "14 command-to-observable items". Enumerate the authoritative list and reconcile the count. |
| CRIT-07 | Pre-Mortem 3 / R3 | change | P2 | Both cite "step S17's MISSION-A.md", but the Work Breakdown defines only S0-S14; MISSION-A.md is **P3**. Dangling reference — retarget to P3. |
| CRIT-08 | C1 | add | P2 | Spec 선행 작업 requires "canon 수정 4건과 **각각의** 구현 기록" (Round 13: "네 건 전부 + 각각 구현 기록"). Plan produces 3 records (047/048/049) for 4 edits by bundling (i)+(ii) into 047. Either split into a fourth record or state explicitly why (i)+(ii) are one behavioural change. |
| CRIT-09 | S10 | change | P2 | `cli/envelope.py:96-121` — `detail` is set whenever traceback lines > `MAX_INLINE_TRACEBACK_LINES` (8, `:23`) and `project_root` is not None, independent of `as_dict()`; `traceback` is set when oversized and no root. A typed failure with a deep stack still emits `detail`, so Build Gate 5 is not guaranteed by typedness alone and the plan's "reliable proxy" claim in Observability is false. |
| CRIT-10 | S6 | add | P2 | `workspace.py:302-316` / `:318-338` — both accessors run `scan.distinct_values`, a `SELECT DISTINCT ... ORDER BY` full-column scan. The membership check adds two full scans per `materialize` on a 4,962-instrument dataset, against the already-strained 30-minute budget (R7). Decide and record the cost strategy (cache, single scan, or accept). |
| CRIT-11 | S1 | change | P3 | `flow/preflight.py` has **4** raise sites (188, 215, 278, 304) carrying **3** distinct values (`preflight.account`, `preflight.execution` ×2 at 215 and 304, `preflight.universe`) — verified. `scan.py` is 7 sites / 7 distinct values. "10 inline stage literals" is a distinct-value count over 11 sites; S1's parenthetical says "3 distinct values" but the headline count invites an agent to lift 10 sites and miss one. State sites and values separately. |
| CRIT-12 | S0 | remove | P3 | Test Plan layer 2 prescribes "for each new constant, a test that the constant equals its historical string" — a literal-equals-literal tautology that passes even if no callsite uses the constant; repo rules forbid tautology tests. Layer 1's hand-maintained code tuple duplicates ~60 existing assertions. Rely on layer 3 plus the unchanged re-run of `tests/data/test_scan.py` / `tests/flow/test_preflight.py`. |
| CRIT-13 | S4 | change | P3 | `domain/errors.py:179-180` — `collector(stage: str, family: FailureFamily = FailureFamily.DATA)`; `family` is already a closed 7-member `StrEnum`, so a `family in FAMILIES` membership check is redundant with the type. State that the enforcement is `stage`-only (plus the `FAMILIES`-mirrors-`FailureFamily` consistency test S13 already plans). |
| CRIT-14 | S12 | add | P2 | `src/vqapr/agent/sample/` contains four shipping modules and `src/vqapr/agent/sample/README.md`. S12 must state that `skill install` ships only `agent/skill/` content and never `agent/sample/` sources, and that manifest sha tracking covers only skill files — otherwise the installer's file set is ambiguous. |

Severity counts: **P1 = 4, P2 = 7, P3 = 3** (14 total).

---

## Claim Checks

Verified true against source: `_COMMANDS` holds 4 verbs (`cli/main.py:19-24`); `add_parser(name)` with no help (`cli/main.py:52`); `cli/run.py:170` calls `args.spec.read_text(...)` before any guard and `:177-181` returns only `occurrences` and `account_version` with no `run_id`; `cli/list_.py:74-75` calls `Workspace.open` unguarded; `collector(stage, family)` is the entry point at `domain/errors.py:179-180`; `_REQUIRED` at `cli/run.py:33`; `_instruments`/`_evaluation_times` perform no membership check (`flow/materialize.py:210-249`); every `test_materialize.py` `materialize()` callsite passes `("A","B")` (lines 99, 123, 146, 169, 197, 230, 256); `publish_run_record` consumes only `final_state.recorder_rows` (`flow/materialize.py:745`); `recorder_rows` is `Mapping[str, tuple[Mapping[str, object], ...]]` (`flow/run_state.py:124`); `envelope.py` sets `family: None` for both `cli.usage` (`:61-62`) and `unhandled` (`:108-109`); `MAX_INLINE_TRACEBACK_LINES = 8` (`:23`); `emit` writes exactly one JSON line (`:125-140`); `_stage_and_publish` refuse-on-existing (`flow/materialize.py:464-474`); lineage payload carries no timestamp and no absolute path (`:362-386`, no `now(`/`utcnow`/`generated_at` in the module).

Verified **false**: `src/vqapr/agent/` holds only an empty `__init__.py` and two README stubs (it holds 7 tracked files including 4 Python modules and a test). `python -m vqapr` is runnable (no `__main__.py`). "17 Build Gate items" (spec lists 16 checkboxes; spec Ontology says 14).

Not verified (out of read-only scope, accepted as given): the ~60 exact-code assertion count; the 37 `Failure.bounded()` callsite count; the 609-passing baseline; all testbed-side facts (`kaist-thesis/`, FRICTION.md, parquet row/date/instrument counts).

## Missing Evidence

- The spec's Technical Context claim about `agent/` contents is contradicted by the repository; the plan inherited it without checking. This is the root of CRIT-01 and CRIT-14.
- No evidence anywhere that a cold `publish` can reach `publish_run_record` without a `SimulationResult`; the carrier shape is unspecified (CRIT-05).
- No evidence that the rung-3 byte-identity comparison is physically constructible under refuse-on-existing (CRIT-03).
- R1 and R4 are both explicitly left unresolved by the plan itself, with resolution deferred to "before S9" and "before S10". Those are real blockers on Build Gate 4 and 13/14, not merely open questions.

## Approval Boundary

**May proceed now, unblocked:** S0 (with CRIT-12 trimming), S1 (with CRIT-11's site/value precision), S2, S5, P1, P4. This is the entire t0 parallel front the plan proposes, and it is sound — the friction-fix lane and the literal lift are independently correct and independently verifiable.

**May proceed after cheap fixes:** S3 (needs bucket names + the `public.py` `__all__` decision), S4 (with CRIT-13), C1/C2/C3 (after CRIT-08's fourth-record decision), S11, S12 (after CRIT-14).

**Outside approval until resolved:** S6 (needs the failure code string and the CRIT-10 cost decision), S7 (the largest gap — must settle run_id, encoding, and the CRIT-03 comparison strategy), S8, S9 (blocked on CRIT-04, CRIT-05, and R1), S10 (blocked on R4 and CRIT-09), S14 (blocked on CRIT-02 and CRIT-03), P2, P3, P5.

## Summary

- **Clarity** — High. Steps carry files, line numbers, changes, and observables; lanes and dependencies are explicit. Two reference defects (S17 dangling, gate-count mismatch).
- **Verifiability** — Mixed. Most observables are genuinely executable. The dominating one (Build Gate 14 / S14) is not, for two independent mechanical reasons.
- **Completeness** — Good on the spec's stated surface: all 16 Build Gate checkboxes and all 8 Spawn Gate conditions have a covering step, and 4 of 5 pre-spawn tasks are fully covered. Incomplete on repository reality (`agent/sample/`) and on the publish call/schema shape.
- **Big Picture** — Strong. D1/D2/D3 are the right drivers, the critical path is correctly identified, and the parallelism decomposition is credible and well-motivated.
- **Principle/Option Consistency** — Principles 1-5 select Option A cleanly. Principle 6 is contradicted by tracked source and must be rescoped.
- **Alternatives Depth** — Genuine. Options B and C get real pros, mechanism-level rejections, and partial absorption rather than dismissal.
- **Risk/Verification Rigor** — R1-R8 are substantive and mostly correct, and Pre-Mortem 2 in particular is excellent diagnosis. Undercut by five unraised risks, two of which (CRIT-02, CRIT-03) block the item the plan itself names as dominating.

## Required Changes

1. **CRIT-01** — Rescope Principle 6 to the new agent surface and explicitly exempt the pre-existing, tested `agent/sample/` package, or add a step that owns its migration and record.
2. **CRIT-02** — Add `src/vqapr/__main__.py` as an owned step, or change S14 to invoke the installed console script and state how the test resolves it.
3. **CRIT-03** — Specify in S7/S14 how the in-process and cold-process publish artifacts coexist for byte-comparison under `_stage_and_publish`'s refuse-on-existing guard.
4. **CRIT-04** — Resolve `publish`'s input surface: positional `<run_id>` (matching Build Gate 14) or YAML spec (matching the spec constraint). State one.
5. **CRIT-05** — Specify the `publish` YAML key list and the carrier object satisfying `publish_run_record`'s `result.final_state.recorder_rows` access.
6. **CRIT-06** — Enumerate the authoritative Build Gate list and reconcile 16 vs 17 vs 14.
7. **CRIT-07** — Retarget the "S17" references in Pre-Mortem 3 and R3 to P3.
8. **CRIT-08** — Produce a fourth implementation record, or justify bundling canon edits (i)+(ii) as one behavioural change.
9. **CRIT-09** — Correct the Observability claim and make S10 guarantee Build Gate 5's no-`detail` condition by mechanism, not by typedness.
10. **CRIT-10** — Decide and record the scan-cost strategy for S6's membership check.
11. **CRIT-11/12/13** — Split site vs value counts in S1; drop the tautology tests in S0/S1 layer 2; state that S4 enforcement is `stage`-only.
12. **CRIT-14** — State S12's installed file set excludes `agent/sample/`.
13. **R1 and R4** must be resolved as part of this revision, not deferred — they gate Build Gate 4 and 13/14, and the plan already schedules their resolution before S9/S10 without owning it in a step.


---

# [stage-02-architect]

# Architect Re-Review — RALPLAN Stage 2 (pass 2), vqapr framework-agent bridge

Reviewed: `stage-02-revision.md` (sha256 `92da98ffe0b70af115aeaec2d39e6a600816a8c8cbdfd0ee51b0a241db3b5ea2`, stage_n 2) as a delta against `stage-01-planner.md` (sha256 `203ba69…`) and against my pass-1 review `stage-01-architect.md` (sha256 `b620c8a2…`). Ratchet rules 1-5 in force. Read-only; no tests, builds, linters, or formatters were run.

## Summary

All five pass-1 P1 blockers are resolved, and resolved *correctly* — I re-verified each answer against source rather than accepting its presence. `run_id = FrozenRun.identity` is right; the parquet-not-JSON argument is right and is in fact stronger than the plan states; the `publish-spec.yaml` source is genuinely derivable from `RecorderManifest`; the membership check is now sited after `Workspace.open`; and the `collector()` guard now raises typed. Two new mechanical defects surface **from the revision's own new commitments** — a latent circular import between `vqapr.descriptors` and `domain/errors.py`, and an internal contradiction between S14's correct "same persisted run" instruction and R11's incorrect "build both roots from one fixture factory" prescription, which cannot produce byte-identity because `run_id` is path-dependent. Neither is P1. Verdict improves from BLOCK to `WATCH`.

## Resolution Audit

| id | sev (p1) | status | verification |
|---|---|---|---|
| ARCH-01 | P1 | **resolved** | Principle 3 + S4(i). Coverage is now a static exhaustiveness test over module-level `*_STAGE` constants; `collector()` is explicitly demoted to runtime supplement. The 6-callsite measurement is reproduced correctly. D1's rationale is corrected from blast-radius to declaration-ordering — and the revision goes further than I asked, noting S4 touches none of the 37 `Failure.bounded()` callsites, so the registry is *low* blast radius. Correct. New risk R10 honestly records the naming-convention dependency the static test introduces. |
| ARCH-02 | P1 | **resolved** | S4(ii) + new Principle 2. `collector()` raises `VqaprError` on a registered meta-stage, never bare `ValueError`. The mechanism is right: `cli/main.py:67-70` catches `Exception`, so an untyped raise would produce `stage:"unhandled"`. Generalizing this into Principle 2 (typed refusal everywhere) is a better fix than I proposed, because it also drives S10's widening. No recursion hazard: constructing `VqaprError` does not re-enter `collector()`. |
| ARCH-03 | P1 | **resolved** | S9 + IR-3. `publish-spec.yaml` written by `run` at persist time. I verified derivability: `RecorderManifest(spec.table_id, spec.fields, …)` at `evidence/recorder.py:96-99` supplies `table_id` and the declared fields; the five `FLOW_ENVELOPE_FIELDS` at `evidence/tables.py:8` are mandatory because `RunRecordSpec.of` rejects the spec without them; `dataset_id` remains the single user choice. The carrier-object answer is also correct — `publish_run_record` reaches only `getattr(getattr(result,"final_state",None),"recorder_rows",None)` at `:745` then `.get(spec.table_id, ())` at `:754`, so a minimal carrier satisfies it. |
| ARCH-04 | P1 | **resolved** | Principle 5 + S7. `run_id = FrozenRun.identity`; the property is at `flow/run.py:374-379` and `_derive_identity` is a sha256 (`:28-29`) over all frozen declarations. Already stamped as `run_id` by `evidence/recorder.py:77`. The reframing of "two identical runs collide" as "identical frozen declarations *are* the same run" is correct. |
| ARCH-05 | P1 | **partially resolved** | S7 and S14 both state the correct instruction — two project roots, same `dataset_id`, **same persisted run**. The supporting evidence is verified: `_lineage_envelope` (`materialize.py:363-386`) emits only `schema_version`, `operation`, `output.{dataset_id,source_id,value_fields}`, `instruments` — no wall-clock, no path — so byte-identity needs no normalizer, exactly as claimed. **But** the new risk R11 prescribes "build both roots from one fixture factory," which contradicts "same persisted run" and cannot work. See ARCH-17. |
| ARCH-06 | P2 | **resolved** | S6's "Files:" line now specifies a new third call sited after `Workspace.open` at `materialize.py:837`, with the correct reason: `_evaluation_times`/`_instruments` run at 835-836 and receive no `project_root`, `Workspace`, or `dataset_id`. Verified against source. |
| ARCH-07 | P2 | **resolved** | S7 gains staging dir, fsync, `os.replace` with `WORKSPACE_SWAP_ATTEMPTS`/`WORKSPACE_SWAP_BACKOFF`, typed refuse-on-existing, and `created_at`. Principle 6 now states explicitly *why* the workspace lock is not reused (unique path, never read-modify-written) rather than omitting it. That is the right call — `workspace.py:829-871`'s lock exists to serialize a read-modify-write cycle that the run directory does not have. |
| ARCH-08 | P2 | **resolved differently than requested** | S8 adds a `runs` kind. The intent is met, but the mechanism I named in pass 1 (`KINDS`/`_ACCESSORS`) was imprecise and the revision adopted it verbatim. See ARCH-18. |
| ARCH-09 | P2 | **resolved differently than requested** | Principle 7 + IR-4 + risk R9. Rather than reconciling `agent/sample/`, the revision scopes the import boundary to the new surface and records the exemption with a full 7-file inventory. Given that `sample/journey.py:15-17` imports `vqapr.extension.fingerprint` and a live test imports these modules, migration would be genuine scope expansion beyond the spec. This is the correct disposition, and R9 honestly records the consequence: the constraint is enforced by review, not by test, for new files. |
| ARCH-10 | P2 | **resolved** | C4 widened to the layout tree (`docs/vqapr-architecture.md:2752-2757`), §13 step 2, and PRD §11.3, with new Principle 8 stating the top-level placement. |
| ARCH-11 | P2 | **resolved** | S6 now carries the literal schema — `explicit:`/`from_dataset:` with a mandatory `start:`/`end:` — moving R1 from "flagging, not fixing" to a decision. The `from_dataset` affordance correctly targets Pre-Mortem 1's real failure mode (hand transcription), which a pure explicit-list rule would have made worse. |
| ARCH-12 | P2 | **resolved** | S11 requires `references/stages.md` to disambiguate `descriptors.STAGES` from the recorder's `OperationRole` `stage` column, naming the `VALUATION` collision explicitly. |
| ARCH-13 | P3 | **resolved** | S10 widened to `cli/new.py:69-71` and `cli/run.py:171-174`, with the 3-tries-per-rung rationale. |
| ARCH-14 | P3 | **resolved** | P5 enumerates all 16 items and names the checklist authoritative over the Ontology row's 14. I re-counted: 1-14 plus 12b, 12c = 16. Correct. |
| ARCH-15 | P3 | **resolved** | Pre-Mortem 3 and R3 now cite P3; no S17 reference remains. |

**Tally: 14 resolved (2 of them differently than requested but correctly), 1 partially resolved, 0 unresolved.**

The Revision Log accounts for all 29 findings and the count is honest — I spot-checked the Critic dispositions I could verify independently. CRIT-09's correction is right: `cli/envelope.py:98-101` writes `detail` when the traceback exceeds `MAX_INLINE_TRACEBACK_LINES` **and** `project_root is not None`, computed from `traceback.format_exception` *before* `as_dict()` is consulted — so `detail` genuinely is not a proxy for untypedness, and S10's shallow-raise mechanism is the right guarantee. CRIT-10's cost claim is right: both accessors go through `scan.distinct_values` (`workspace.py:302-316`, `:318-338`). CRIT-11's site/value split is right: `scan.py` 7 sites / 7 distinct values, `preflight.py` 4 sites / 3 distinct (`preflight.execution` at both 215 and 304) = 11 sites / 10 values.

## New Findings

Three, each with its rule-2 novelty justification. None is P1.

### ARCH-16 — `vqapr.descriptors` and `domain/errors.py` form a latent import cycle (P2)

**Novelty (rule 2).** Not raisable at pass 1: `stage-01-planner.md` S3 said only "declare `STAGES`, `FAMILIES`, `VERBS`" without stating that `FAMILIES` mirrors `FailureFamily`, and S4 did not state that `collector()` reads the registry from `descriptors`. The revision specifies both for the first time (S3: "`FAMILIES` … mirroring `FailureFamily`'s 7 members"; S4: "`collector()` validates `stage ∈ FAILURE_STAGES`"), and it is their conjunction that creates the cycle.

**Evidence.** `domain/errors.py` today imports nothing from vqapr — only `uuid`, `collections.abc`, `dataclasses`, `enum` (`:10-13`). `FailureFamily` is defined there at `:19-28`. S4 requires `domain/errors.py` to import `vqapr.descriptors`; if `descriptors` in turn imports `FailureFamily` to build `FAMILIES`, the import is circular and fails at module load, because the `from` statement executes before `FailureFamily` is bound.

**Why P2, not P1.** It is avoidable by construction and the fix is one line of specification, not a redesign. It is not certain to occur — a literal `frozenset({"DATA", "INTENT", …})` has no cycle.

**Fix.** State in S3 that `descriptors` imports nothing from `vqapr.domain`: `FAMILIES` is declared as literal strings, and "mirrors `FailureFamily`'s 7 members" is asserted only in `tests/domain/test_stage_registry.py`, which may import both. This is the same discipline Principle 8 already applies to `agent/` — the revision simply has not extended it to `domain/`.

### ARCH-17 — R11 contradicts S14 and prescribes a two-root setup that cannot be byte-identical (P2)

**Novelty (rule 2).** The two-root strategy did not exist at pass 1 — it is my own ARCH-05 recommendation, adopted here. R11 is new text introduced by this revision. The defect is in R11's elaboration of that strategy, so it could not have been raised before.

**Evidence.** S14 and S7 give the correct instruction: "same `dataset_id`, **same persisted run**." R11 then says the test "must build both roots from one fixture factory" — i.e. seed and run in each root. That cannot yield byte-identity, because `run_id` is path-dependent:

- `cli/register.py:139` resolves a relative source path as `declared if declared.is_absolute() else base / declared`, where `base` is the declaration's own directory — an absolute, per-root path.
- `FrozenRun._derive_identity` includes `"sources": [(source.source_id, str(source.path), …)]` and `execution_input.source`'s `str(...path)`.
- Therefore two independently seeded roots produce **different** `run_id` values, even from byte-identical declarations.
- That difference is not cosmetic: `evidence/recorder.py:77` stamps `run_id` onto every recorded row, so it is a published **value field** (it is one of the five mandatory `FLOW_ENVELOPE_FIELDS`), and `materialize.py:805` derives `payload["record"]["run_identity"]` from `row["run_id"]`. Both the parquet and the lineage JSON would differ.

The test would then fail for a reason having nothing to do with cold-process fidelity — precisely the false negative S14 exists to avoid.

**Why P2, not P1.** S14's own instruction ("same persisted run") is correct, so an implementer following the step rather than the risk note will build the right test. This is a contradiction to remove, not an unexecutable plan.

**Fix.** Replace R11 with the mechanism the instruction implies: persist the run **once** in root A, then copy `.vqapr/runs/<run_id>/` into root B and publish from that copy. Root B needs only a workspace that opens and does not already hold `dataset_id`. Restate R11's residual as what it actually is — the two roots must not diverge in any field `_lineage_envelope` carries — and note explicitly that re-running in root B is forbidden.

### ARCH-18 — `list runs` cannot use the `_ACCESSORS` mechanism (P3)

**Novelty (rule 2).** This originates in my own pass-1 ARCH-08 wording ("Add `runs` to `KINDS`/`_ACCESSORS`"), which the revision adopted verbatim in S8. The imprecision only became a concrete implementation instruction in this revision.

**Evidence.** `cli/list_.py:75` dispatches as `items = getattr(workspace, _ACCESSORS[args.kind])`, so every kind must name a `Workspace` property. Runs are not workspace declarations — they live on disk under `.vqapr/runs/` and `Workspace` exposes no `runs` property (its accessors are datasets, sources, execution_inputs, components, agendas, strategy_configs, valuation_configs, monitoring_policies).

**Fix.** S8 should say `runs` is a kind handled *before* the `_ACCESSORS` lookup — enumerate `.vqapr/runs/*/manifest.json` and summarize `run_id`, `created_at`, `tables` — rather than adding an entry to `_ACCESSORS`. Keep the same `success("workspace.list", …)` envelope shape so the verb stays uniform.

## Analysis

**The revision improved the argument, not just the text.** Three places where it went beyond what I asked and got it right:

1. **Principle 2** generalizes ARCH-02 from "what `collector()` raises" into "typed refusal everywhere," which then correctly drives S10's widening to `new.py` and the spec-shape raises. That is the right abstraction of a point I made narrowly.
2. **The parquet argument is stronger than stated.** S7 says JSON makes cold publish *fail validation*. I verified the chain: `publish_run_record` sets `available_at` from `row["event_time"]` (`materialize.py:774-777`), and `_stage_and_publish` runs `validate(candidate_registration, candidate_source)` then `raise_if_failed()` (`:527-529`) against a registration declaring `available_at` as the time column. A string would fail there. This converts Pre-Mortem 2 from a byte-comparison worry into a typed failure — a genuinely better test.
3. **Dropping the two pass-1 test layers (CRIT-12)** is correct and I endorse it against my own pass-1 position, which listed them without objection. The mechanical argument the revision substitutes is sound: `collector()` merely constructs `_Collector`, whose `done()` passes `stage` through to `Diagnosis`; `code` strings are assembled independently at the 37 `Failure.bounded()` callsites and never traverse `collector()`. A membership check there provably cannot rewrite a code. That is a proof, not a test, and it is worth more than the tautology it replaces.

**On the intent-reconciliation candidates.** All five are genuine spec-vs-source conflicts rather than scope creep, and raising them for user confirmation is the right handling. IR-1 is the important one: it preserves the spec's placement decision exactly while adding the coverage mechanism that makes it hold. IR-4 is the one the orchestrator should look at hardest, because it converts a stated constraint into a review-enforced one — R9 says so plainly, which is the honest framing.

**Scope discipline.** The revision added exactly one step (S15) and split one (C1→C1/C2), both traceable to accepted findings. Step count 21 is consistent with S1-S15 + C1-C4 + P1-P5. Pass 1's S0 was removed and its id not reused, as stated.

## Root Cause

Not applicable at this pass — the pass-1 root cause (treating the spec's *safe* validation point as the *complete* one) is corrected at its source in Principle 3 and D1, and the correction propagates consistently through S4, the Test Plan, and IR-1. The two new P2 findings share a shallower cause: both are places where a newly specified mechanism was not traced to the one line of existing code it must interoperate with (`domain/errors.py`'s import list; `cli/list_.py:75`'s dispatch).

## Findings

| findingId | targetId | action | severity | finding | evidence |
|---|---|---|---|---|---|
| ARCH-16 | S3 | change | P2 | `descriptors` declaring `FAMILIES` as a mirror of `FailureFamily` while `collector()` imports `FAILURE_STAGES` creates a circular import that fails at module load. State that `descriptors` imports nothing from `vqapr.domain`; assert the mirror in the test instead. | `domain/errors.py:10-13` (no internal imports today), `:19-28` (`FailureFamily`); revision S3, S4 |
| ARCH-17 | S14 | change | P2 | R11's "build both roots from one fixture factory" contradicts S14's "same persisted run" and cannot produce byte-identity: `run_id` is path-dependent, and it is both a published value field and the source of the lineage `run_identity`. Replace with persist-once-then-copy the run directory. | `cli/register.py:139`; `flow/run.py` `_derive_identity` `sources` block; `evidence/recorder.py:77`; `flow/materialize.py:805`; revision R11 vs S14/S7 |
| ARCH-18 | S8 | change | P3 | `runs` cannot be an `_ACCESSORS` entry — that mechanism dispatches to a `Workspace` property and runs live on disk, not in the workspace. Handle the kind before the lookup by enumerating `.vqapr/runs/*/manifest.json`. | `cli/list_.py:75`, `:16-35`; revision S8 |

## Recommendations

1. **ARCH-17 first.** It touches the dominating acceptance item. One paragraph rewrite of R11, plus a sentence in S14 forbidding a re-run in root B.
2. **ARCH-16.** One sentence in S3. Cheap now, an import error later.
3. **ARCH-18.** One sentence in S8.
4. **Carry IR-1 through IR-5 to the user as written.** They are correctly identified and correctly scoped; IR-4 deserves the most attention because it downgrades a spec constraint to review enforcement.
5. **No further structural change.** The plan's shape, sequencing, and step decomposition are sound and should not be reopened.

## Tradeoffs

| Tension | Revision's resolution | Assessment |
|---|---|---|
| Registry coverage vs. the spec's `collector()`-only placement | Static test for coverage, `collector()` as runtime supplement, raised as IR-1 | **Correct.** Preserves the settled decision while making it hold. The honest framing in IR-1 is what makes this safe to confirm. |
| `agent/sample/` migration vs. scope | Exempt, evidence-backed, risk R9, raised as IR-4 | **Correct given scope.** Migration would expand beyond the spec. The cost — no repo-wide boundary test this cycle — is named rather than hidden. |
| Build Gate 4 literal text vs. the one-JSON-line contract | `--out` replaces the stdout redirect, raised as IR-2 | **Correct.** The envelope contract is load-bearing for the entire agent-facing design; the redirect is incidental. |
| `publish <run_id>` vs. YAML-spec input | `run` writes `publish-spec.yaml`; positional id resolves to it, raised as IR-3 | **Correct and verified derivable.** Satisfies both surfaces without inferring anything the user must choose. |
| Two-root byte comparison vs. `run_id` path-dependence | Instruction right (S14), elaboration wrong (R11) | **Partially resolved** — see ARCH-17. The mechanism exists; the plan must name it unambiguously. |

## Architectural Status

WATCH

## Code Review Recommendation

COMMENT


---

# [stage-02-critic]

# RALPLAN Stage 2 — Critic Re-Review (pass 2)

Reviewed: `stage-02-revision.md` (sha256 `92da98ffe0b70af115aeaec2d39e6a600816a8c8cbdfd0ee51b0a241db3b5ea2`, stage_n 2) as a delta against `stage-01-planner.md` (sha256 `203ba69…`) and my pass-1 review `stage-01-critic.md` (sha256 `2ef65916…`, ITERATE, 14 findings). Counter-review of `stage-02-architect.md` (sha256 `854e80b7…`) per ratchet rule 5. Ratchet rules 1-5 in force. Read-only; no tests, builds, linters, or formatters run.

## Verdict

**OKAY**

All four of my pass-1 P1 blockers are resolved, and resolved against source rather than by assertion — I re-verified each answer independently rather than accepting its presence in the Revision Log. Nothing remaining is P1. Five open items exist (the Architect's three, plus two of mine), and every one of them is a one-line correction with the fix already named, discoverable by an implementer on first run, and requiring no invented scope. The five intent-reconciliation candidates are genuine spec-vs-source conflicts that belong with the user, not in another planning pass.

Per the lane instruction: **the remaining items are errata and intent reconciliation, not grounds for a revision pass.** I state that explicitly. Apply the five named corrections as errata before execution and route IR-1 through IR-5 to the user; do not reopen the plan's shape.

---

## Resolution Audit

| id | sev (p1) | status | verification |
|---|---|---|---|
| CRIT-01 | P1 | **resolved** | Principle 7 rescopes the import boundary to the new surface (`agent/skill/`, `agent/targets.py`) and records `agent/sample/` as an explicit pre-existing exemption, reproducing the exact 7-file inventory and the import lines I cited (`sample/journey.py:15-17`, `sample/exchange.py:13`, `tests/agent/test_sample_panel.py:16-23`). Critically it adds the sentence I needed: "no boundary test may be written that fails against it." Risk R9 records the consequence honestly — the constraint is review-enforced, not test-enforced, for new files. Raised to the user as IR-4. This is exactly the disposition I asked for. |
| CRIT-02 | P1 | **resolved** | New step **S15** adds `src/vqapr/__main__.py`, and S14's deps now include S15. I re-verified the premise: no `__main__.py` exists, `pyproject.toml [project.scripts]` declares only `vqapr = "vqapr.cli:main"`, and `src/vqapr/__init__.py` is empty — so `python -m vqapr` fails today and the added module is the minimal fix. S15's stated rationale (deterministic invocation independent of PATH/venv console-script resolution, which is fragile on Windows inside a test) is the right reason to prefer it over the console script. |
| CRIT-03 | P1 | **resolved** *(with a new contradiction introduced elsewhere — see below)* | S7 and S14 both specify two project roots, same `dataset_id`, same persisted run, citing `materialize.py:464-474`. The supporting claim is verified: `_lineage_envelope` (`:362-386`) emits only `schema_version`, `operation`, `output.{dataset_id,source_id,value_fields}`, `instruments` — no wall-clock, no absolute path — so byte-identity needs no normalizer. My finding is answered. The revision then introduced a *new* contradiction in risk R11's elaboration of that strategy, which the Architect caught as ARCH-17; I endorse it below rather than double-counting it here. |
| CRIT-04 | P1 | **resolved** | S9 states one surface: positional `<run_id>` with an optional `--spec PATH` override, reconciled with the spec's YAML-input constraint by having `run` write `publish-spec.yaml` at persist time. Build Gate 14 becomes literally executable without abandoning the constraint. Raised as IR-3. |
| CRIT-05 | P2 | **resolved** | S9 specifies the carrier object exposing exactly `.final_state.recorder_rows` and the publish YAML key list. Verified: `publish_run_record` reaches through `getattr(getattr(result,"final_state",None),"recorder_rows",None)` at `materialize.py:745` then `recorded.get(spec.table_id, ())` at `:754`; `FLOW_ENVELOPE_FIELDS` is the 5-member frozenset `{run_id, producer_id, stage, event_time, sequence}` at `evidence/tables.py:8`; `RecorderManifest` carries `table_id` at `evidence/recorder.py:16-19`. The derivability claim holds. |
| CRIT-06 | P2 | **resolved** | P5 enumerates all 16 items literally (1-14 plus 12b, 12c) and names the checklist authoritative over the Ontology row's 14. I re-counted independently against the spec: 16. Settled. |
| CRIT-07 | P2 | **resolved** | Pre-Mortem 3 and R3 now cite **P3**. No dangling `S17` reference remains; the only occurrence is the retrospective note in P3 describing the fix. |
| CRIT-08 | P2 | **resolved** | Canon edits split into four steps C1-C4 with four records 047-050, matching the spec's "네 건 전부 + 각각 구현 기록" (Round 13). |
| CRIT-09 | P2 | **resolved** | The Observability section retracts the "reliable proxy" claim outright and replaces it with the `cli/envelope.py:96-121` mechanism. S10 now guarantees Build Gate 5 **by mechanism** — raising shallowly in the CLI handler so the traceback stays under `MAX_INLINE_TRACEBACK_LINES` — and tests assert key absence directly rather than inferring it from typedness. This is the correct fix, not a reword. |
| CRIT-10 | P2 | **resolved** *(claim inaccurate — see CRIT-16)* | S6 records the cost decision explicitly and cross-references R7's budget. The decision is sound; one arithmetic claim inside it does not survive the CLI/flow split, which I raise as a new P3 below. |
| CRIT-11 | P3 | **resolved** | S1 states sites and values separately with the miss-one hazard named. Re-verified against source: `scan.py` 7 sites / 7 distinct values (146, 279, 308, 343, 394, 487, 693); `preflight.py` 4 sites / 3 distinct values (188, 215, 278, 304, with `preflight.execution` at both 215 and 304). 11 sites / 10 values. Correct. |
| CRIT-12 | P3 | **resolved** | Both layers dropped. The Test Plan now rests on the mechanical argument plus the unchanged re-run of the two suites. I re-verified the argument: `collector()` at `domain/errors.py:178-179` merely constructs `_Collector`, whose `done()` passes `stage` through to `Diagnosis`; codes are assembled at the 37 `Failure.bounded()` callsites and never traverse it. That is a proof and it is worth more than the tautology it replaces. |
| CRIT-13 | P3 | **resolved** | S4 states enforcement is `stage`-only; `FAMILIES` mirroring `FailureFamily` is retained as a consistency test only. Correct — `family: FailureFamily` is a closed `StrEnum` (`domain/errors.py:19-28`) and `collector`'s signature already types it (`:178`). |
| CRIT-14 | P2 | **resolved** | S12 states the installed set is `agent/skill/` content only, never `agent/sample/` sources, with manifest sha tracking scoped to skill files. A test is added in `tests/agent/test_manifest.py`. |

**Tally: 14 of 14 resolved. 0 partially resolved, 0 unresolved, 0 resolved differently than requested.** No carryover blockers under rule 4.

The Revision Log's "29 accepted, 0 rejected" is honest for the Critic half; I verified each of my 14 dispositions against the artifact body rather than the log line, and in every case the body contains the substantive change the log claims.

---

## Architect Counter-Review

Rule 5 requires me to judge whether the Architect's three new findings are justified under rule 2 or are scope inflation, and whether its resolution calls are accurate.

**No scope inflation found. All three findings are justified, correctly severity-scoped, and independently verified by me against source. I say this plainly because rule 5 exists to stop inflated demands from forcing revision passes — that is not what happened here.** All three are P2/P3, each names a one-line fix, and the Architect explicitly recommends against reopening the plan's structure (Recommendation 5). Two of the three are self-corrections of its own pass-1 imprecision, which is the opposite of inflation.

### ARCH-16 — descriptors/errors import cycle (P2) — **justified**

Rule-2 novelty holds. Pass-1 `stage-01-planner.md` S3 said only "declare `STAGES`, `FAMILIES`, `VERBS`" and did not state that `FAMILIES` mirrors `FailureFamily`; pass-1 S4 did not state that `collector()` reads the registry from `descriptors`. The revision specifies both for the first time, and it is their conjunction that creates the cycle. Could not have been raised at pass 1.

I verified the mechanism independently: `src/vqapr/domain/errors.py:9-13` imports only `uuid`, `collections.abc`, `dataclasses`, `enum` — nothing from vqapr — and `FailureFamily` is defined in that same module at `:19-28`. If `descriptors` imports `FailureFamily` to build `FAMILIES` while `errors.py` imports `FAILURE_STAGES` from `descriptors`, the `from` statement executes before `FailureFamily` is bound and module load fails.

I checked one thing the Architect did not, which *narrows* the finding in the plan's favour: `src/vqapr/__init__.py` is **empty**, so importing `vqapr.descriptors` does not drag in the package surface. The cycle is therefore exactly as tightly scoped as ARCH-16 claims — it exists only if `descriptors` itself imports from `vqapr.domain`, and vanishes entirely if `FAMILIES` is declared as literal strings. P2 is right: avoidable by construction, one line of specification, not certain to occur.

### ARCH-17 — R11 contradicts S14 (P2) — **justified, and the most valuable finding of the pass**

Rule-2 novelty holds trivially: the two-root strategy is new text in this revision (it is my CRIT-03 / the Architect's ARCH-05 recommendation, adopted here), and R11 is the elaboration that did not exist at pass 1.

I verified the path-dependence chain end to end:
- `cli/register.py:137-139` — `declared if declared.is_absolute() else base / declared`, where `base` is the declaration's own directory, i.e. per-root.
- `flow/run.py:492-495` — `_derive_identity` includes `"sources": [(source.source_id, str(source.path), source.hive_partitioned) …]`, and `:404-405` does the same for the execution input's source path.
- `evidence/recorder.py:77` — `run_id` is stamped onto every recorded row, and it is one of the five mandatory `FLOW_ENVELOPE_FIELDS` (`evidence/tables.py:8`), so it is a published value field.
- `flow/materialize.py:805` — `payload["record"]["run_identity"]` is derived from `row["run_id"]`.

So two independently seeded roots produce different `run_id` values from byte-identical declarations, and that difference propagates into both the parquet and the lineage JSON. R11's "build both roots from one fixture factory" therefore cannot yield byte-identity, and the test would fail for a reason unrelated to cold-process fidelity — the exact false negative S14 exists to prevent.

The proposed fix (persist once in root A, copy `.vqapr/runs/<run_id>/` into root B, publish from the copy, forbid a re-run in root B) is sound. I checked it does not break byte-identity by another route: the lineage `source_id` is `f"record-{spec.dataset_id}"` (`materialize.py:794`), which is root-independent, and the absolute output path never enters the payload. P2 is right, because S14's own step text is correct and an implementer following the step rather than the risk note builds the correct test.

### ARCH-18 — `list runs` cannot use `_ACCESSORS` (P3) — **justified**

Rule-2 novelty holds, and this is the Architect correcting its own pass-1 wording, which the revision adopted verbatim into S8. Self-correction, not inflation.

Verified: `cli/list_.py:27-35` maps every kind to a `Workspace` property name, and `:75` dispatches `getattr(workspace, _ACCESSORS[args.kind])`. The eight accessors are datasets, sources, components, agendas, execution_inputs, strategy_configs, valuation_configs, monitoring_policies — there is no `runs` property, and runs live on disk under `.vqapr/runs/`. Adding `"runs"` to `_ACCESSORS` yields an `AttributeError`. P3 is right: an implementer hits it immediately and routes around it.

### Resolution tally

**I agree with the Architect's tally of 14 resolved (2 differently than requested), 1 partially resolved, 0 unresolved.** I counted its table independently and it reconciles to 15.

- The **ARCH-05 "partially resolved"** call is accurate and is the correct severity judgement — the instruction in S7/S14 is right and the elaboration in R11 is wrong, which is precisely "partially," not "unresolved."
- The **ARCH-08 "resolved differently than requested"** call is accurate and commendably self-implicating: the intent (recoverable run ids) is met, the mechanism it originally named was wrong, and it says so.
- The **ARCH-09 "resolved differently than requested"** call is accurate and I concur with its reasoning: migrating `agent/sample/` would be genuine scope expansion beyond the spec, so exemption plus an honest R9 is the correct disposition. This matches my own CRIT-01 position.

One further point of agreement worth recording: the Architect endorses dropping the two pass-1 test layers (my CRIT-12) *against its own pass-1 position*, which had listed them without objection. That is the right call and the right way to make it.

---

## Acceptance Criteria Traceability (delta)

Only gate items whose covering step changed. **Authoritative count is now settled at 16** (items 1-14 plus 12b and 12c), enumerated literally in P5, with the spec Ontology row's "14" explicitly overruled. My CRIT-06 is closed. **Newly uncovered gate items: 0.** The pass-1 position of 0 uncovered holds.

| # | What changed | Covering step now | Assessment |
|---|---|---|---|
| 3 | Canon ownership split across two records | S5, legitimized by **C1** (docstring) + **C2** (PRD §2.6) | Improved — C1/C2 split per CRIT-08 |
| 4 | **Gate text amended**: `> spec.yaml` → `--out spec.yaml` | S10(d) | Correct resolution of R4. Writing raw YAML to stdout would break the one-JSON-line guarantee at `cli/envelope.py:125-140`. This amends an approved acceptance criterion, so **IR-2 is the right channel** — user confirmation, not a planning pass |
| 5 | Guarantee mechanism changed from typedness to shallow-raise | S10(b) | Correct per CRIT-09. Verified `envelope.py:96-121` writes `detail` on traceback length + non-None root, independent of `as_dict()` |
| 6 | Coverage mechanism changed: static exhaustiveness test primary, `collector()` demoted to runtime supplement | S4(i)+(ii) | Materially strengthened. Verified the premise: `collector(` appears at exactly 6 callsites in 3 files — `data/datasets.py:86,117,171`, `exchange/execution_table.py:129,164`, `testing/conformance/runner.py:157` — so `collector()` alone could never have made this gate honest. Raised as IR-1 |
| 7 | Three named buckets with `STAGES` as flat union; `descriptors` deliberately excluded from `public.py.__all__` | S3 | Correct. The `__all__` decision is right — `tests/boundaries/test_public.py:181-322` asserts exact tuple equality over 105 names, and Build Gate 7 imports `vqapr.descriptors` directly anyway |
| 12/12b/12c | Installed file set explicitly excludes `agent/sample/` | S12 | Improved per CRIT-14 |
| 13 | `run_id = FrozenRun.identity`, not minted; `publish-spec.yaml` written at persist time; `list runs` added | S6 + S8 + S9 | Materially strengthened. Verified `identity` at `flow/run.py:373-378` and `frozen` in scope at `cli/run.py:176`, so the envelope change is genuinely one line |
| 14 | **Unblocked.** New step S15 supplies the entrypoint; two-root strategy supplies the comparison | S9 + S14 + **S15** | Both pass-1 mechanical blockers now owned by steps. Contingent on ARCH-17's R11 correction |

**Spawn Gate delta.** Only rung 3 changed: byte-identity now has a named mechanism (two roots, same persisted run) plus a sharper sub-assertion — cold-process `available_at` must read back as a timestamp, not a string. I verified this is a real validation failure and not merely a byte difference: `publish_run_record` sets `available_at` from `row["event_time"]` (`materialize.py:774-777`) and `_stage_and_publish` runs `validate(...)` then `raise_if_failed()` (`:520-521`). The parquet-not-JSON mandate in S7 is therefore load-bearing, and the revision's reasoning is correct.

**Scope check.** The revision adds exactly one step (S15) and splits one (C1→C1/C2), both traceable to accepted findings; 21 steps reconciles as S1-S15 + C1-C4 + P1-P5. Pass-1's S0 is removed per CRIT-12 with its id not reused. `vqapr list runs` (ARCH-08) is a new capability with no gate item of its own, but it is justified rather than creep: Build Gate 14 requires the id **in a new shell**, and today it is emitted once and then undiscoverable. C4's widening to the architecture layout tree, §13 step 2, and PRD §11.3 is drift correction for the same decision, correctly surfaced as IR-5 because it touches sections the spec did not enumerate. **No scope creep found.**

---

## New Findings

Two, both P3, both rule-2 justified, neither blocking. I am deliberately not re-issuing ARCH-16/17/18 as Critic findings — I endorse them above and double-counting would inflate the apparent remaining work.

### CRIT-15 — S14/S7 do not state what root B must contain (P3)

**Rule-2 novelty.** The two-root strategy is new text in this revision, adopted from my own CRIT-03. The question "what must the second root already contain" only becomes askable once that strategy exists.

**Evidence.** `publish_run_record` calls `Workspace.open(project)` at `flow/materialize.py:741`, before any other work, and the shared authority calls `workspace.register_dataset(candidate_registration, final_source)` at `:532`. So root B is not an empty directory: it needs an initialized workspace that opens successfully and does **not** already hold `dataset_id` (`materialize.py:838-846` refuses a duplicate output `dataset_id` at the input stage). S7's byte-comparison paragraph and S14 both say "two separate project roots" without stating this precondition.

**Fix.** One sentence in S14: root B must be an initialized workspace that does not already register `dataset_id`, and — per ARCH-17 — must receive the run directory by copy rather than by re-running. Rides along with ARCH-17's rewrite.

### CRIT-16 — S6's "zero additional scans" cost claim does not survive the CLI/flow split (P3)

**Rule-2 novelty.** Pass-1 S6 had neither a YAML schema nor a cost decision — it said only "verify membership." Both the `from_dataset` affordance and the "resolve each accessor exactly once per `materialize` call" claim are introduced by this revision, so the arithmetic could not have been checked at pass 1.

**Evidence.** S6 states the cost is "zero additional scans" on the `from_dataset` path because expansion and membership check reuse one accessor result. But the two live on opposite sides of an API boundary. `materialize(project_root, component_id, spec, *, evaluation_times, instruments)` receives already-concrete sequences, and S6 sites the check as a new call *inside* `flow/materialize.py` after `Workspace.open` at `:837`. The `from_dataset` expansion must therefore happen in the S9 CLI verb, which calls `Workspace.instruments()`/`evaluation_times()` to expand; the in-flow check then calls them again to verify. `Workspace.instruments()` (`workspace.py:302-316`) and `evaluation_times()` (`:318-338`) each run a fresh `scan.distinct_values` `SELECT DISTINCT … ORDER BY` with no memoization. That is up to 4 full-column scans, not 0.

**Why P3 and not P2.** The check is still correct; only the cost estimate is wrong, it is bounded, and it is on the rung-2 path only. But R7 already flags the 30-minute Build Gate budget as asserted-not-measured, and this quietly doubles the scan cost the budget must absorb, so it should be stated accurately rather than optimistically.

**Fix.** Either memoize the two accessors on `Workspace`, or site the membership check in the CLI verb where the expansion already holds the result, or restate the cost as "up to 4 scans; 2 when instruments and times are both explicit." Any of the three is fine; the plan should pick one.

---

## Findings

| findingId | targetId | action | severity | evidence |
|---|---|---|---|---|
| CRIT-15 | S14 | add | P3 | `flow/materialize.py:741` (`Workspace.open(project)` before all other work), `:532` (`register_dataset`), `:838-846` (duplicate `dataset_id` refused at input stage). Revision S7 byte-comparison paragraph and S14 say "two separate project roots" without stating root B's required initial state. Add one sentence: root B is an initialized workspace not already registering `dataset_id`, receiving the run directory by copy. |
| CRIT-16 | S6 | change | P3 | `workspace.py:302-316` and `:318-338` both call `scan.distinct_values` with no memoization; `materialize()` takes concrete sequences so the `from_dataset` expansion happens in the S9 CLI verb while S6 sites the check inside `flow/materialize.py` after `:837`. "Zero additional scans" is therefore up to 4. Pick one of: memoize on `Workspace`, site the check in the CLI, or restate the cost. Cross-reference R7. |

Severity counts: **P1 = 0, P2 = 0, P3 = 2.**

Endorsed from the Architect lane, not re-issued here: **ARCH-16** (P2, S3, import cycle), **ARCH-17** (P2, S14/R11 contradiction), **ARCH-18** (P3, S8 `_ACCESSORS`). Combined open work across both lanes: **5 findings, 0 P1, 3 P2, 2 P3.**

---

## Approval Boundary

**Execution may proceed on the full plan**, subject to five one-line errata applied before the affected step starts:

1. **S3** — state that `descriptors` imports nothing from `vqapr.domain`; declare `FAMILIES` as literal strings and assert the `FailureFamily` mirror in `tests/domain/test_stage_registry.py` only (ARCH-16). Must land before S4.
2. **R11 / S14** — replace "build both roots from one fixture factory" with persist-once-in-root-A-then-copy-the-run-directory, and forbid a re-run in root B (ARCH-17). Must land before S14.
3. **S8** — handle the `runs` kind before the `_ACCESSORS` lookup by enumerating `.vqapr/runs/*/manifest.json`, keeping the `success("workspace.list", …)` envelope shape (ARCH-18).
4. **S14** — state root B's required initial state (CRIT-15). Rides with erratum 2.
5. **S6** — correct or restate the scan-cost claim (CRIT-16).

**Routed to the user, not to planning:** IR-1 through IR-5. All five are genuine spec-vs-source conflicts where the source contradicts an assumption the approved spec encoded, and each preserves intent while changing mechanism. IR-4 deserves the closest attention because it converts a stated constraint (`constraint:no-import`) into a review-enforced one for this cycle; R9 says so plainly, which is the honest framing. IR-2 deserves the second-closest look because it amends the literal text of an approved Build Gate item.

**Outside approval:** nothing. No step is blocked on unresolved design.

---

## Summary

- **Clarity** — High and materially improved. S7 is now a specification rather than a deferral, which was pass 1's single largest gap; S6 carries a literal YAML schema; P5 enumerates its 16 items instead of asserting a count.
- **Verifiability** — Resolved. Every pass-1 unexecutable observable now has a mechanism: S15 supplies the entrypoint, the two-root strategy supplies the comparison, and the `available_at`-as-timestamp sub-assertion converts a byte-diff worry into a typed validation failure.
- **Completeness** — All 16 Build Gate items covered, all 8 Spawn Gate conditions covered, all 5 pre-spawn tasks covered (the 4-edits/4-records gap closed by C1-C4).
- **Big Picture** — Unchanged and sound. D1's rationale was corrected from blast-radius to declaration-ordering; the conclusion survives on a truer argument, which is the right way to absorb a falsified premise.
- **Principle/Option Consistency** — Resolved. Principle 7 no longer asserts something the repository contradicts, and new Principle 8 (top-level `descriptors`) plus Principle 2 (typed refusal everywhere) are both correct generalizations rather than patches.
- **Alternatives Depth** — Unchanged from pass 1 and still genuine.
- **Risk/Verification Rigor** — Improved. R1, R2, and R4 moved from open to resolved with stated decisions; R9, R10, R11 are new and honest, including R10's admission that the static exhaustiveness test depends on a naming convention and leaves runtime-parameter stages on non-`collector()` paths unguarded by either mechanism. R11 is the one that needs correcting, per ARCH-17.

## Required Changes

None that require another planning pass. The five items in the Approval Boundary are errata to apply in place; IR-1 through IR-5 are for user confirmation. I recommend the orchestrator apply the errata and carry the IRs to the user rather than commissioning a pass 3.


---

# [stage-03-architect]

# Architect Re-Review — RALPLAN Stage 3 (pass 3, errata), vqapr framework-agent bridge

Reviewed: `stage-03-revision.md` (sha256 `57e1a548343fe8416d0a8af6057f3c5012632ce08f1aa26ce0757ff6d2f7f2d2`, stage_n 3) as a delta against `stage-02-revision.md` (sha256 `92da98ff…`) and against my pass-2 review `stage-02-architect.md` (sha256 `854e80b7…`). Ratchet rules 1-5 in force. Read-only; no tests, builds, linters, or formatters were run.

## Summary

All five errata are closed, and each is closed *correctly* — I re-verified every supporting citation against source rather than accepting it as stated. ARCH-05's pass-1 partial is now fully closed by the ARCH-17 rewrite. Two residual defects remain, both P3, both cosmetic, both fixable at landing without another planning pass: the artifact says "21 steps" where it enumerates 24 (an error I myself validated at pass 2), and CRIT-15's rationale cites a line range inside `materialize()` for a guard that belongs to `_stage_and_publish`. Neither changes an instruction, a dependency, or a gate. Verdict improves from `WATCH` to `CLEAR`.

## Errata Audit

| item | sev | status | verification |
|---|---|---|---|
| **ARCH-05** (pass-1 partial) | P1 | **closed** | The partial was never in the instruction — it was R11's elaboration contradicting it. That contradiction is gone (see ARCH-17 below). I re-verified the supporting claim the plan now cites in two places: `_lineage_envelope` (`materialize.py:363-386`) emits only `schema_version`, `operation`, `output.{dataset_id,source_id,value_fields}`, `instruments` — no wall-clock, no absolute path. The added claim that lineage `source_id` is root-independent is also correct: `source_id = f"record-{spec.dataset_id}"` at `:795`. Byte-identity genuinely needs no normalizer. |
| **ARCH-16** | P2 | **closed** | S3 now states `descriptors` imports nothing from `vqapr.domain`, declares `FAMILIES` as literal strings, and defers the mirror assertion to `tests/domain/test_stage_registry.py`. Verified the premise: `domain/errors.py` imports only stdlib (`uuid`, `collections.abc`, `dataclasses`, `enum`) and `FailureFamily` is defined at `:19-28`, so S4's `from descriptors import FAILURE_STAGES` plus a reverse import would fail at module load. The cycle does not exist today and the plan now forbids creating it. Principle 8 correctly generalized from "descriptors sits at top level" to "registry modules sit below their consumers and import nothing from them." A guard assertion is added to `tests/agent/test_descriptors.py`, and S3 is marked as landing before S4. |
| **ARCH-17** | P2 | **closed** | R11 is rewritten end to end; the fixture-factory framing is gone. Every load-bearing citation checks out: `cli/register.py:137-139` resolves a relative source path as `declared if declared.is_absolute() else base / declared` where `base` is the declaration's own directory; `_derive_identity` includes `str(source.path)` in both the `sources` block and the `execution_input.source` block (`flow/run.py:404-405`, `:492-495`); `evidence/recorder.py:77` stamps `run_id` onto every row; `evidence/tables.py:8` makes it one of the five mandatory `FLOW_ENVELOPE_FIELDS`; and `materialize.py:805` derives `payload["record"]["run_identity"]` from `row["run_id"]`. The path-dependence argument is sound and the persist-once-then-copy protocol is the correct remedy. |
| **ARCH-18** | P3 | **closed** | S8 no longer says "add `runs` to `_ACCESSORS`". It now specifies `runs` in `KINDS` (needed — that is the argparse `choices` tuple) but handled **before** the `_ACCESSORS` lookup, enumerating `.vqapr/runs/*/manifest.json` and keeping the `success("workspace.list", …)` envelope. The rationale is verified: `cli/list_.py:75` dispatches `getattr(workspace, _ACCESSORS[args.kind])`, all eight existing kinds name a real `Workspace` property, and no `runs` property exists — an `_ACCESSORS` entry would raise `AttributeError`. |
| **CRIT-15** | P3 | **closed, with a mis-citation** | Root B's required initial state now appears in both S7's byte-comparison paragraph and S14 step 3, worded identically: an initialized workspace that opens successfully and does not already register `dataset_id`. The requirement is correct and the instruction is actionable. Two of three citations are accurate (`Workspace.open(project)` at `materialize.py:741`; `register_dataset` at `:532`). The third, `:838-846`, names the wrong function — see ARCH-20. |
| **CRIT-16** | P3 | **closed** | The "zero additional scans" claim is withdrawn and replaced with an honest figure. I re-derived it independently and it is right: `materialize()` (`:824`) takes already-concrete `evaluation_times`/`instruments` sequences, so `from_dataset` expansion must happen in the S9 CLI verb while `_require_membership` runs inside the flow after `:837` — opposite sides of an API boundary. Neither `Workspace.instruments()` (`workspace.py:302-316`) nor `evaluation_times()` (`:318-338`) memoizes; both call `scan.distinct_values` fresh. (`_decode_cached` memoizes workspace YAML decoding only, not scans.) So 2 scans for expansion + 2 for the check = **4** on the `from_dataset` path, **2** when both are explicit. Option 3 (restate honestly, keep the check in the flow) is the right call: it protects direct `public.py` callers who bypass the CLI, and the plan says so. |

**Tally: 6 of 6 open items closed.**

## Consistency Check

**Persist-once-then-copy — S7, S14, R11 agree.** All three now state one protocol with no daylight between them:

- **S7** — "The run is executed and persisted **exactly once, in root A**. Root B does **not** re-run: it receives `.vqapr/runs/<run_id>/` by directory copy and publishes from that copy. Re-running in root B is **forbidden**."
- **S14** — six numbered steps: seed and run once in root A (1), publish in-process in root A (2), prepare root B (3), **copy** the run directory (4), publish cold in a new subprocess (5), compare byte-for-byte (6). Step 4 carries the explicit "Do **not** re-run in root B".
- **R11** — retitled to what it actually guards ("the two roots must not diverge in any field the lineage carries"), states the run is executed exactly once so `run_id` is identical by construction, and closes with "Explicitly forbidden: re-running the run in root B… Pass 2's 'build both roots from one fixture factory' prescribed exactly that and was wrong."

No contradiction remains. The self-correction in R11 is the right way to record a reversed decision.

**Other cross-references touched this pass, all consistent.** S6 ↔ R7 ↔ P2 tell one cost story (up to 4 scans on the `from_dataset` path, 2 explicit; R7 names the doubled cost; P2 gains the timing task). S3 ↔ S4 ↔ the two registry test files state one import direction. S8's `list runs` mechanism appears in exactly two places (S8 and the Integration test list) and agrees in both.

**Counts.** Build Gate items: 1-14 plus 12b, 12c = **16** ✓ (matches P5's enumeration). Risks R1-R11 = **11** ✓ (only R7 and R11 retexted, as claimed). Intent Reconciliation IR-1…IR-5 = **5** ✓, wording unchanged from pass 2 as claimed — I diffed them.

**Steps: the one count that does not hold.** The artifact says "21 steps" in three places; a structural search returns **24** step headings (S1-S15 = 15, C1-C4 = 4, P1-P5 = 5). Every step is present and correctly labelled — only the total is wrong. See ARCH-19.

**Line-citation drift (advisory, no finding).** A few citations sit ±1-2 lines off the current source: `flow/run.py:373-378` for the `identity` property (actually `:374-379`), `domain/errors.py:179-180` in S4 vs `:178-179` in the Test Plan (actually `:178-179`), `materialize.py:794` for the lineage `source_id` (actually `:795`). All resolve to the right construct on sight. Not worth a finding; noted so the Critic sees I checked.

## New Findings

Two, both P3. Neither is a design defect and neither warrants a fourth planning pass.

### ARCH-19 — "21 steps" where 24 are enumerated (P3)

**Novelty (rule 2).** This error entered at **pass 2**, when S0 was removed (CRIT-12), S15 was added (CRIT-02), and C1 was split into C1/C2 (CRIT-08) — the arithmetic was not re-run after the split. I validated "21" as correct in my own pass-2 review and did not recount. It surfaces now only because this assignment explicitly directs me to confirm no count broke, which sent me to enumerate rather than trust. I raise it as a correction of my own miss, not as a defect this errata pass introduced.

**Evidence.** Header line, Work Breakdown heading, and the pass-3 re-derived-counts paragraph all say 21. Enumeration: S1-S15 + C1-C4 + P1-P5 = 24. A structural search over the artifact returns exactly 24 step headings.

**Impact.** Cosmetic. No dependency, lane assignment, or gate mapping is affected; no step is missing. The only risk is a downstream reader using the header as a checksum against the enumeration and concluding three steps were dropped.

**Fix.** Replace 21 with 24 in the three places. Landing-time token change.

### ARCH-20 — CRIT-15's rationale cites a range inside `materialize()`, not `publish_run_record()` (P3)

**Novelty (rule 2).** The CRIT-15 root-B-initial-state text is **new in this pass** — it did not exist at pass 1 or 2, so the citation could not have been checked before.

**Evidence.** S7 and the Revision Log justify "root B must not already register `dataset_id`" partly by citing "`:838-846` refuses a duplicate at the input stage." That range is the `dataset_exists` guard inside `materialize()`, which begins at `:824` and opens its workspace at `:837`. `publish_run_record()` (`:717-819`) has **no** `dataset_exists` check — it goes from `Workspace.open(project)` at `:741` straight to the `isinstance` check and then to row assembly. The requirement is nonetheless correct, enforced by two other mechanisms: `_stage_and_publish` raises `materialize.publish.path_exists` at `:466-474` when either output path exists, and `workspace.register_dataset` at `:532` raises a conflict if the id is registered with a different declaration. The other two citations in the same sentence (`:741`, `:532`) are accurate.

**Impact.** None on execution. S14 step 3's instruction is correct and actionable as written; only the supporting reference is misattributed. It matters solely because an implementer chasing the citation lands in `materialize()` and may conclude `publish` has a guard it does not have.

**Fix.** Replace `:838-846` with `:466-474` (path_exists), keeping `:532`. Landing-time edit.

## Findings

| findingId | targetId | action | severity | finding | evidence |
|---|---|---|---|---|---|
| ARCH-19 | Work Breakdown | change | P3 | Artifact states "21 steps" in three places; the work breakdown enumerates 24 (S1-S15 + C1-C4 + P1-P5). All steps present and correct — only the total is wrong. Entered at pass 2 after S0's removal, S15's addition, and the C1/C2 split; I validated it then and missed it. | `stage-03-revision.md` header, Work Breakdown heading, pass-3 re-derived-counts paragraph; structural search returns 24 step headings |
| ARCH-20 | S7 | change | P3 | CRIT-15's rationale cites `materialize.py:838-846` for a guard that lives in `materialize()`, not `publish_run_record()`, which has no `dataset_exists` check. Requirement is correct; the citation should be `:466-474` (path_exists) plus the already-correct `:532`. | `flow/materialize.py:717-819` (no dataset_exists), `:741`, `:466-474`, `:532`, `:824`, `:838-846` |

## Analysis

**The errata pass did what an errata pass should.** No settled section was restructured, no IR wording moved, no step was added or renumbered, and the two risks that changed text (R7, R11) are exactly the two the findings required. Scope discipline is clean.

Two things it did better than the minimum:

1. **R11 records its own reversal.** Rather than quietly replacing the fixture-factory text, it names the prior prescription and says it was wrong. A future reader who encounters the pass-2 artifact will not re-derive the discarded approach.
2. **CRIT-16 chose the honest restatement over the convenient fix.** Memoizing on `Workspace` or relocating the check into the CLI would have made the number smaller; both would have cost the safety property for direct `public.py` callers. The plan takes the two extra scans, says why, and cross-references R7 in both directions so the Build Gate budget carries the cost rather than hiding it. That is the right trade and it is argued, not asserted.

**On the two residual P3s.** Both are documentation accuracy, not design. Neither changes what an implementer does: ARCH-19 leaves every step correctly enumerated, and ARCH-20 leaves S14 step 3's instruction correct. Under rule 4, neither approaches the P1 bar ("unexecutable or produces a wrong result"), and under the disposition guidance, holding `WATCH` over two landing-time token edits would stall the workflow for no gain.

**What genuinely remains open is not a planning question.** IR-1 through IR-5 are unchanged and correctly scoped; they need a *user* decision, not another revision. IR-4 remains the one deserving the closest attention, because it converts a stated spec constraint into a review-enforced one — R9 says so plainly, which is the honest framing. The residual risks (R1's calendar intersection, R2's unbounded `.vqapr/runs/` growth, R3's adapter-follow-through, R9's exemption, R10's naming-convention dependency) are all named, bounded, and correctly deferred. None is a gap the plan should close before execution.

## Root Cause

Not applicable. The pass-1 root cause was corrected at pass 2 and the correction has held through two passes. The two residual P3s share a shallow cause — a count not re-run after a split, and a citation not re-resolved after being moved into new prose — and neither indicates a reasoning defect in the plan.

## Architectural Status

CLEAR

## Code Review Recommendation

APPROVE


---

# [stage-03-critic]

# RALPLAN Stage 3 — Critic Re-Review (pass 3, errata)

Reviewed: `stage-03-revision.md` (sha256 `57e1a548343fe8416d0a8af6057f3c5012632ce08f1aa26ce0757ff6d2f7f2d2`, stage_n 3) as a delta against `stage-02-revision.md` (sha256 `92da98ff…`) and my pass-2 review `stage-02-critic.md` (sha256 `3599e143…`, OKAY). Counter-review of `stage-03-architect.md` (sha256 `638f8847…`, CLEAR/APPROVE) per rule 5. Ratchet rules 1-5 in force. Read-only; no tests, builds, linters, or formatters run.

## Verdict

**OKAY**

Both of my pass-2 findings are closed, and closed against source rather than by assertion. Nothing remaining is P1 or P2. Everything open is a landing-time token edit, and the substantive open questions (IR-1 through IR-5) belong to the user, not to another planning pass. **I state that explicitly, as the lane instruction directs: the residual items are cosmetic errata fixable at landing plus intent reconciliation with the user. A fourth planning pass would be waste.**

Verdict holds at OKAY (rule 3 satisfied — no regression, and this errata pass introduced no defect that would justify one).

One thing the punch list must carry that the Architect did not catch: **its own line-drift advisory is wrong on two of three items**, and applying it wholesale at landing would corrupt two currently-correct citations. Detail below.

---

## Errata Audit

### CRIT-15 — root B's required initial state — **closed**

Stated in **two** places, worded consistently, which is what makes it robust to an implementer reading only one:

- **S7**, byte-comparison paragraph: "**Root B's required initial state:** an initialized workspace that opens successfully … and that does **not** already register `dataset_id`."
- **S14 step 3**: "Prepare root B: an initialized workspace that opens successfully and does **not** already register `dataset_id` (CRIT-15)."

I re-verified the requirement itself rather than the prose. `publish_run_record` calls `Workspace.open(project)` at `flow/materialize.py:741` as its first action — before the `isinstance` check, before row assembly — so root B must hold an openable workspace. `_stage_and_publish` then calls `workspace.register_dataset(candidate_registration, final_source)` at `:532`, so the id must be registrable. Both cited lines are accurate. The requirement is correct and the instruction is actionable.

One of the three supporting citations is misattributed — the Architect caught it as ARCH-20 and I confirm it independently below. That does not reopen CRIT-15: the *requirement* is right, only a reference pointer is wrong.

### CRIT-16 — the scan-cost claim — **closed, and closed better than I asked**

I offered three options (memoize, relocate the check, or restate honestly). The plan chose restatement and — unlike a minimal compliance edit — supplied the engineering reason I had not:

> "We accept that cost rather than memoizing on `Workspace` or relocating the check, because keeping the check inside the flow is what protects direct `public.py` callers who bypass the CLI entirely — the safety property is worth more than two scans."

I verified this justification is sound, because it is the part that could have been hand-waved. `materialize` is a public API surface, so a Python caller can invoke it without ever touching `cli/materialize.py`. Had the membership check been relocated into the CLI verb to save two scans, Pre-Mortem 1's silent-wrong-answer bug would remain reachable through the public API — the check would guard the agent path and leave the library path exposed. Keeping it in the flow is correct, and paying two scans for it is the right trade.

The arithmetic is now right, and I re-derived it independently: `materialize()` (`:824`) receives already-concrete `evaluation_times`/`instruments` sequences, so `from_dataset` expansion happens in the S9 CLI verb while `_require_membership` runs inside the flow after `:837` — opposite sides of an API boundary, so no result can be shared. Neither `Workspace.instruments()` (`workspace.py:302-316`) nor `evaluation_times()` (`:318-338`) memoizes; both call `scan.distinct_values` fresh. 2 for expansion + 2 for the check = **4** on the `from_dataset` path, **2** when both are explicit. Exactly as stated.

The cost is cross-referenced in both directions — R7 now names the doubled scan cost, and P2 gains the timing task ("Also time rungs 1–3 against R7's budget, given S6's honest scan cost"). That closes the loop I asked for.

**Tally: 2 of 2 Critic errata closed. 0 not closed.**

---

## Architect Counter-Review

### Is `CLEAR` justified? — **Yes.**

I independently re-verified all four errata that were not mine, and the Architect's closure calls are accurate in each case:

- **ARCH-16** (import cycle) — S3 now states `descriptors` imports nothing from `vqapr.domain`, declares `FAMILIES` as literal strings, and defers the mirror assertion to `tests/domain/test_stage_registry.py`. Premise re-verified: `domain/errors.py:9-13` imports only stdlib and `FailureFamily` is defined at `:19-28`, so the reverse import would fail at module load. Principle 8's generalization from "descriptors sits at top level" to "registry modules sit below their consumers and import nothing from them" is the right abstraction. S3 is marked as landing before S4.
- **ARCH-17** (persist-once-then-copy) — R11 is rewritten end to end, the fixture-factory framing is gone, and S7 / S14 / R11 now state one protocol. I re-verified the path-dependence chain that makes this necessary: `cli/register.py:137-139` resolves relative source paths against the declaration's own directory; `_derive_identity` includes `str(source.path)` in both the `execution_input.source` block (`flow/run.py:404-405`) and the `sources` block (`:492-495`); `evidence/recorder.py:77` stamps `run_id` on every row; `evidence/tables.py:8` makes it a mandatory `FLOW_ENVELOPE_FIELDS` member; `materialize.py:805` derives the lineage `run_identity` from it. Sound.
- **ARCH-18** (`list runs`) — S8 now specifies `runs` in `KINDS` (correct — that is the argparse `choices` tuple, verified at `cli/list_.py:16-25`) but handled **before** the `_ACCESSORS` lookup. Verified `cli/list_.py:27-35` maps all eight kinds to real `Workspace` properties and `:75` dispatches via `getattr`, so an `_ACCESSORS` entry for `runs` would raise `AttributeError`. Correct.
- **ARCH-05** (pass-1 partial) — genuinely closed by the ARCH-17 rewrite. The instruction was always right; only R11's elaboration contradicted it, and that contradiction is gone.

No P1 or P2 remains in either lane. Clearing here is correct, not early. Holding `WATCH` over two token edits would stall the workflow for no gain, and the Architect says so in those terms.

### ARCH-19 — "21 steps" where 24 are enumerated — **real, correctly scoped P3, and it is a documentation error, not evidence of uncounted steps**

The lane instruction asks me to distinguish these two, because they have different consequences. I enumerated rather than trusting anyone's arithmetic, including my own.

A structural search for step headings returns exactly **24**: S1-S15 (15) at lines 117, 123, 128, 135, 140, 145, 152, 162, 168, 176, 183, 188, 194, 199, 211; C1-C4 (4) at 216, 221, 226, 231; P1-P5 (5) at 238, 241, 244, 247, 250. The artifact says "21" in three places (header, Work Breakdown heading, re-derived-counts paragraph).

**It is a documentation error.** The decisive evidence is that the enumeration is *complete and closed*: every step id in each range is present with a full body, there is no gap in any sequence, and every dependency reference resolves to an enumerated step (S3→S1,S2; S4→S3; S6→S3,S4; S8→S4,S7; S9→S6,S8; S10→S4,S9; S11→S3; S12→S3,S11; S14→S9,S10,S15; C1/C2→S5; C3→S12; C4→S4; P2→S6; P3→S11). Nothing was added without a body, and nothing referenced is missing. The parallelism summary independently names every lane member. Only the total is wrong.

Origin confirmed: pass 2 removed S0 (CRIT-12), added S15 (CRIT-02), and split C1 into C1/C2 (CRIT-08), and the total was not re-run. Pass 1 was 23 (S0-S14 + C1-C3 + P1-P5); pass 2 should have been 24. "21" matches no pass. **I validated "21" in my own pass-2 review and did not recount — this is my miss as much as the Architect's**, and I record it rather than letting the correction read as one-sided.

Consequence for an implementation agent: bounded. Because every step is enumerated and dependency-closed, an agent working the list executes all 24. The only failure mode is an agent using the header as a checksum and concluding three steps were dropped. P3 is right.

### ARCH-20 — CRIT-15 rationale mis-citation — **real, correctly scoped P3, genuinely cosmetic**

Confirmed independently, and I read the full function body rather than trusting the range. `publish_run_record` spans `:717-819`: `Workspace.open` at `:741`, `isinstance` check at `:742-743`, the `recorder_rows` getattr at `:745`, the empty-table guard at `:754-762`, row assembly at `:765-792`, lineage at `:794-807`, `_stage_and_publish` at `:807`, return at `:814`. There is **no** `dataset_exists` check anywhere in it. The cited `:838-846` sits inside `materialize()`, which begins at `:824` and opens its workspace at `:837`.

The requirement survives on two other mechanisms, both real: `_stage_and_publish` raises `<publish>.path_exists` at `:466-474` when either output path exists, and `workspace.register_dataset` at `:532` is where a conflicting id would surface. The other two citations in the same sentence (`:741`, `:532`) are accurate.

Cosmetic is the right call: S14 step 3's instruction is correct and executable as written, and only a supporting pointer is misattributed. The concrete harm is narrow — an implementer chasing the citation lands in `materialize()` and may wrongly conclude `publish` carries a `dataset_exists` guard it does not have. P3.

### Where the Architect is wrong — its line-drift advisory is 1 of 3 correct

The Architect flagged three citations as "±1-2 lines off" under "advisory, no finding." I checked all three with anchored searches because an advisory that reaches a landing punch list gets applied. **Two of the three are wrong, and applying them would corrupt currently-correct citations.**

| Citation | Plan says | Architect says | Truth | Who is right |
|---|---|---|---|---|
| `identity` property | `flow/run.py:373-378` | "actually `:374-379`" | `:373` is `@property`, `:374` is `def identity`, `:378` is `return self._identity`, `:379` is blank | **Plan.** 373-378 is decorator-through-return. The Architect's range starts at `def` and ends on a blank line |
| lineage `source_id` | `materialize.py:794` | "actually `:795`" | `:794` is `source_id = f"record-{spec.dataset_id}"`; `:795` is `payload = _lineage_envelope(` | **Plan.** The Architect's line points at the wrong statement |
| `collector` | S4 says `domain/errors.py:179-180`; Test Plan says `:178-179` | "actually `:178-179`" | `:178` is `def collector(...)`, `:179` is the return | **Architect.** S4 is off by one |

So the one real drift is inside the plan (S4), and the Architect's two "corrections" would introduce drift that does not currently exist. This is not scope inflation — the Architect explicitly declined to raise it as a finding, which is the correct severity instinct — but it is an inaccuracy that becomes harmful the moment it is acted on. **Punch-list item 5 exists to prevent that.**

### Resolution tally

**I agree with the Architect's tally of 6 of 6 closed.** I verified all six independently: ARCH-05, ARCH-16, ARCH-17, ARCH-18 by re-reading source, and CRIT-15/CRIT-16 as my own findings above. Its two "resolved differently" style calls do not arise this pass, and its single P1-legacy item (ARCH-05) is genuinely closed rather than deferred.

---

## Landing Punch List

Six items. All are token edits or one-sentence additions. **None requires a planning pass, and none blocks starting execution** — items 1-4 can be applied to the artifact at landing, and items 3-4 only matter before S4 and S13 respectively.

| # | id | Edit |
|---|---|---|
| 1 | **ARCH-19** | Replace "21" with **24** in three places: the header line ("step count is unchanged at 21"), the Work Breakdown heading ("**21 steps**: S1–S15, C1–C4, P1–P5"), and the pass-3 re-derived-counts paragraph. All 24 steps are present and dependency-closed; only the total is wrong. |
| 2 | **ARCH-20** | In S7's byte-comparison paragraph and the Revision Log's CRIT-15 row, replace `materialize.py:838-846` with **`:466-474`** (the `path_exists` guard in `_stage_and_publish`). Keep `:741` and `:532` — both accurate. |
| 3 | **CRIT-18** *(new, P3)* | In S4's "Files:" line, change `src/vqapr/domain/errors.py:179-180` to **`:178-179`**. `def collector` is at `:178`. The Test Plan already says `:178-179`; this pass corrected the Test Plan and left S4 behind, so the artifact now contradicts itself. Apply before S4 starts. |
| 4 | **CRIT-17** *(new, P3)* | In the Test Plan's `tests/agent/test_descriptors.py` bullet, name the mechanism for the new import-direction guard: it must run in a **clean subprocess** probing `sys.modules`, not in-process. Cite `tests/boundaries/test_capability_absence.py:79-103` as the working precedent. Apply before S13's descriptors test is written. |
| 5 | **(counter-review)** | **Do not apply** the Architect's line-drift advisory for `flow/run.py:373-378` or `materialize.py:794`. Both plan citations are correct and the proposed "corrections" are wrong. Only the third item in that advisory is real, and it is punch-list item 3. |
| 6 | **(advisory, no finding)** | S5 and S8 both modify `cli/list_.py`. S5 adds the empty-workspace guard around `Workspace.open` (`:74`); S8 adds the `runs` kind handled before the `_ACCESSORS` lookup (`:75`). Whichever lands second should confirm the `runs` branch is evaluated before the S5 guard can short-circuit to `count:0`. Not a defect — a run cannot exist without a workspace, so the case is unreachable in practice — but the two edits touch adjacent lines in different lanes. |

---

## New Findings

Two, both P3, both rule-2 justified as introduced or newly exposed *by this errata pass*. The bar at pass 3 is high and I have applied it: I discarded several observations that were merely restatements of settled ground.

### CRIT-17 — the new import-direction guard test needs a subprocess, and in-process it is guaranteed to mislead (P3)

**Rule-2 novelty.** The guard assertion is new text this pass. Pass-2's `tests/agent/test_descriptors.py` bullet said only "`vqapr.descriptors` imports without importing `vqapr.agent`"; pass 3 adds "**and without importing `vqapr.domain`** (the import-cycle guard, ARCH-16)." The mechanism question arrives with the new clause.

**Evidence.** Asserting `"vqapr.domain" not in sys.modules` inside the pytest process is guaranteed-red and says nothing about the module under test, because the suite imports `vqapr.domain` long before any assertion here would run. The repo has already solved exactly this and documented why, at `tests/boundaries/test_capability_absence.py:7-13`: "The capability half runs in a **clean subprocess**, because the in-suite process is useless for the question: `conftest` imports duckdb session-wide and `vqapr.public` pulls in the data, flow and evidence layers long before any assertion here would run. Asserting absence in that process would be guaranteed-red." The working pattern is at `:86-103` — build a probe string, run it under `sys.executable`, print the intersection of `sys.modules` with a forbidden set.

This is favourable ground for the plan: `src/vqapr/__init__.py` is **empty**, so `import vqapr.descriptors` drags in nothing by itself and the probe gives a clean, meaningful answer.

**Why P3.** The precedent is discoverable and an implementer who writes the naive version gets an immediate red and finds the neighbouring file. Cheap to prevent, cheaper than debugging.

**Fix.** Punch-list item 4.

### CRIT-18 — S4's `collector` citation now contradicts the Test Plan's (P3)

**Rule-2 novelty.** The *inconsistency* is new this pass. Pass 2 cited `domain/errors.py:179-180` in both S4 and the Test Plan — wrong, but internally consistent. Pass 3 corrected the Test Plan to `:178-179` and left S4 at `:179-180`, so the artifact now disagrees with itself about the same function.

**Evidence.** `def collector(stage: str, family: FailureFamily = FailureFamily.DATA) -> _Collector:` is at `src/vqapr/domain/errors.py:178`; `:179` is the return. The Test Plan's `:178-179` is right; S4's `:179-180` is off by one and points past the function.

**Why P3.** S4's "Files:" line names the correct file and the correct function by name; the range is a pointer, not an instruction. No behaviour changes.

**Fix.** Punch-list item 3.

---

## Findings

| findingId | targetId | action | severity | evidence |
|---|---|---|---|---|
| CRIT-17 | S13 | add | P3 | Test Plan's `tests/agent/test_descriptors.py` bullet adds "without importing `vqapr.domain`" but names no mechanism. In-process the assertion is guaranteed-red and uninformative — see `tests/boundaries/test_capability_absence.py:7-13` for the repo's own statement of why, and `:86-103` for the clean-subprocess `sys.modules` probe pattern. `src/vqapr/__init__.py` is empty, so the probe is clean. Name the subprocess mechanism and cite the precedent. |
| CRIT-18 | S4 | change | P3 | S4 "Files:" cites `src/vqapr/domain/errors.py:179-180`; `def collector` is at `:178` and the return at `:179`. The Test Plan was corrected to `:178-179` this pass while S4 was not, so the artifact contradicts itself. Change S4 to `:178-179`. |

Severity counts: **P1 = 0, P2 = 0, P3 = 2.**

Endorsed from the Architect lane, not re-issued: **ARCH-19** (P3), **ARCH-20** (P3). Combined open work across both lanes: **4 findings, 0 P1, 0 P2, 4 P3** — all landing-time token edits, plus one counter-review instruction (punch-list item 5) to *not* apply two incorrect Architect corrections.

---

## Approval Boundary

**Execution may proceed on the full plan.** No step is gated on a planning question. Punch-list items 1-2 are artifact hygiene and may be applied at any time. Item 3 should land before S4 and item 4 before S13's descriptors test — both are one-line edits inside steps that have not started.

**Routed to the user, not to planning:** IR-1 through IR-5, verbatim and unchanged since pass 2 (I diffed them; the plan's claim that no erratum altered an IR's wording holds). IR-4 remains the one deserving closest attention, because it converts a stated spec constraint (`constraint:no-import`) into a review-enforced one for this cycle — R9 states that consequence plainly rather than burying it. IR-2 is second, because it amends the literal text of an approved Build Gate item.

**Named and correctly deferred, not gaps:** R1's calendar-intersection residual, R2's unbounded `.vqapr/runs/` growth, R3's adapter follow-through with its stated contingency, R9's exemption, R10's naming-convention dependency, R11's divergence constraint. Each is bounded and none should be closed before execution.

---

## Summary

- **Delta discipline** — Clean. No settled section restructured, no IR wording moved, no step added or renumbered, and exactly the two risks the findings required (R7, R11) changed text. An errata pass that stayed an errata pass.
- **Closure quality** — High. Every erratum is closed with the reasoning recorded inline, not just the correction. R11 names its own reversed prescription as wrong, so a reader who meets the pass-2 artifact will not re-derive the discarded fixture-factory approach.
- **CRIT-16 in particular** — The plan chose the honest number over the convenient one and argued the trade (protecting direct `public.py` callers) rather than asserting it, then propagated the cost into R7 and P2 so the Build Gate budget carries it visibly instead of hiding it. That is the right call and it is the one place this pass improved the engineering rather than the prose.
- **Residual** — Four P3 documentation items across both lanes and one instruction not to apply two incorrect corrections. Nothing touches an instruction, a dependency, or a gate.

## Required Changes

None that require another planning pass. Apply the six-item landing punch list and carry IR-1 through IR-5 to the user. I recommend the orchestrator finalize on that basis rather than commissioning a pass 4.

