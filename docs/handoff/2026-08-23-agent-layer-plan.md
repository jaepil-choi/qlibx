# RALPLAN Stage 3 (revision pass 3) — vqapr framework-agent bridge

Scope source: `.gjc/_session-01a0271d-70c6-7000-bdee-8573530e757e/specs/deep-interview-vqapr-agent-layer.md` (18 rounds, 4.4% ambiguity, PASSED). Repo `C:/Users/chlje/DevProjects/qlibx`, branch `jaepil-develop`, head `2918fb9`. Revises `stage-02-revision.md` (sha256 `92da98ff…`). Pass-2 join: Critic **OKAY** (14/14 resolved), Architect **WATCH/COMMENT** (14 resolved, 1 partial). This is a targeted errata pass closing 5 findings (0 P1, 3 P2, 2 P3). Nothing settled has been restructured; step count is unchanged at **24** (S1-S15 = 15, C1-C4 = 4, P1-P5 = 5).

## RALPLAN-DR Summary

### Principles (invariants any correct implementation must hold)

1. **One envelope, always.** Every CLI path returns exactly one JSON line and exit 0/1 through `cli/envelope.py:emit`. Guard-before-open is mandatory for every verb: `cli/run.py:170` reads the spec with `read_text` before any guard, so a missing file becomes `stage:"unhandled"`.
2. **Typed refusal, everywhere, including the registry itself.** Any guard added by this work must raise `VqaprError` carrying a registered stage — never a bare `ValueError`/`TypeError`/`FileExistsError`. `cli/main.py:67-70` catches `Exception` and routes it to `envelope.failure`, so an untyped raise re-creates `unhandled` one layer out. This is why validation stays out of `Failure.__post_init__`, and it applies with equal force to `collector()`'s own new check.
3. **Registry coverage is static; the runtime check is a supplement.** `collector(` is called at only 6 sites (`data/datasets.py:86,117,171`, `exchange/execution_table.py:129,164`, `testing/conformance/runner.py:157`). Every stage the Build Gate exercises — `workspace.open.missing`, `preflight.*`, `materialize.*` — builds `VqaprError` directly and bypasses it. Coverage therefore comes from a **static exhaustiveness test** over every module-level `*_STAGE` constant; `collector()` validation is the runtime guard the spec settled on, not the coverage mechanism. See Intent Reconciliation IR-1.
4. **CLI owns usage, skill owns remedy.** `cli/main.py`'s docstring forbids the CLI from explaining anything and points at the skill; progressive disclosure forbids the skill from duplicating verb detail. The cycle breaks by authority split: argparse `help=`/`description=` is *usage* and belongs to the CLI; "what to do about it" is *remedy* and belongs to `SKILL.md`.
5. **Narrow persistence, content-addressed identity.** `run` persists `final_state.recorder_rows` + manifest + finalization provenance only, never `SimulationResult`. The run's identity is **not minted**: `FrozenRun.identity` (`flow/run.py:373-378`, sha256 over frozen declarations) is already stamped as the `run_id` column on every recorder row (`evidence/recorder.py:77`, consumed at `flow/materialize.py:805`). A second id would give one run two identities.
6. **Reuse existing conventions whole, not by half.** `.vqapr/runs/<id>/` reuses the atomic temp→fsync→`os.replace` protocol with the `WORKSPACE_SWAP_ATTEMPTS`/`WORKSPACE_SWAP_BACKOFF` retry loop (`workspace.py:63-64,1014-1037`). The workspace **lock** protocol (`workspace.py:47-61,829-855`) is deliberately *not* reused, because the run directory path is unique per run and never read-modify-written — stated explicitly rather than omitted.
7. **The `agent/` import boundary scopes over the NEW surface only.** New files — `agent/skill/`, `agent/targets.py` — must not be imported from any deterministic package path, and must import nothing beyond `vqapr.descriptors` and package metadata. **`agent/sample/` is an explicit pre-existing exemption**: `git ls-files src/vqapr/agent/` returns 7 tracked files including `sample/{build,exchange,journey,reversal_5d}.py`; `sample/journey.py:15-17` imports `vqapr.extension.fingerprint` and `vqapr.public`; `sample/exchange.py:13` imports `vqapr.public`; and `tests/agent/test_sample_panel.py:16-23` imports them. This code is tracked, tested, and outside this cycle's scope. No step migrates it, and **no boundary test may be written that fails against it**.
8. **Registry modules sit below the layers that consume them, and import nothing from them.** `vqapr.descriptors` lives at package top level, not inside `agent/`, because Principle 7 forbids `domain/` importing `agent/` and `collector()` in `domain/errors.py` must read the registry. The same discipline runs downward: **`descriptors` imports nothing from `vqapr.domain`** (see S3). The architecture doc currently contradicts the placement and is corrected in C4.

### Decision Drivers (top 3)

- **D1 — Declaration ordering, not blast radius.** The registry must exist before `materialize`/`publish` mint new stage strings, otherwise those strings get declared twice — once as literals, once retrofitted. Pass 1 justified registry-first by "every failure path flows through `collector()`", which the source falsifies (Principle 3). The conclusion survives on a truer argument and is in fact strengthened: S4 touches none of the 37 `Failure.bounded()` callsites, so the registry is *low* blast radius, and the real depth is S1 (the literal lift) + S3 (the declaration), both mechanical.
- **D2 — Build Gate item 14 is the dominating acceptance item.** `vqapr publish <run_id>` in a new shell returning `ok:true` transitively asserts the template emitter (4), the registry (6/7), all three rungs (13), and the cold-process boundary. Both pass-1 mechanical blockers — no runnable module entrypoint, and refuse-on-existing foreclosing the byte comparison — are now owned by S15 and S7 respectively.
- **D3 — Two spawns cost real wall-clock and are not cheaply repeatable.** Anything that would produce a vqapr-attributable `blocked` entry must be retired before spawn; discovering it during spawn burns the measurement.

### Viable Options for the overall execution shape

**Option A — Registry-first (RECOMMENDED).**
Order: lift inline literals → `vqapr.descriptors` + static exhaustiveness test + `collector()` runtime guard → friction fixes → new verbs → skill CLI → SKILL.md → canon edits → pre-spawn freeze.
- Pros: satisfies D1's declaration-ordering constraint — the two new verbs are born inside the registry. S1 is a genuine precondition for any registry completeness claim. The static exhaustiveness test lands early, so Build Gate 6/7 become honestly assertable rather than assertable-on-paper. Low risk: S4 touches no `code` string.
- Cons: no user-visible progress until the verb lane opens; front-loads the least interesting work. Mitigated by four genuine parallel fronts at t0.

**Option B — Verbs-first.** Attacks D2's critical path first and gives the run-persistence design maximum settling time. **Invalidated as primary**: new verbs would mint stage strings before the registry exists, and Build Gate 6 could not be asserted for them until the end. Its insight is absorbed — S7 is now a fully specified decision rather than deferred design work.

**Option C — Friction-fixes-first.** Cheapest visible win; fixes (a) and (c) are genuinely independent. **Invalidated as an overall shape**: fix (d)'s template emitter must emit a `materialize` spec for a verb that does not exist yet, and fix (b) needs a registered stage to report into. Its independent half is salvaged as the parallel F lane.

**Recommendation: Option A**, with the F lane (S5), the canon lane, S15, and P1/P4 running in parallel from t0.

## Pre-Mortem (exactly 3 scenarios)

### Scenario 1 — The agent completes rung 2 with a silently wrong panel.

**Narrative.** Agent B fills `instruments` with a plausible ticker list, partly hand-transcribed and partly stale. `flow/materialize.py:_instruments` (230-249) accepts it: it rejects invalid identities, empty, and duplicates, but performs no membership check. Only *total* mismatch trips `materialize.output.empty` (893-900). A 60%-overlap list publishes a 60%-coverage panel, writes both artifacts, and exits 0. Rung 2's coverage criterion fails while the transcript shows a clean `ok:true`.

**Earliest observable signal.** Per-instrument `actual_rows` at `flow/materialize.py:352-355` is non-zero for the matching subset and absent for the rest — evidence that exists in-process and is currently discarded rather than judged.

**Prevented by.** S6 (membership check sited *after* `Workspace.open`) plus S13's six new tests. Critically, S6's schema (`from_dataset` + mandatory date range) removes the hand-transcription that *is* this failure mode: the agent expresses "the whole universe for this quarter" without typing 4,962 tickers.

### Scenario 2 — `publish` works in-process and fails cold.

**Narrative.** `run` persists via JSON. Build Gate 13 passes in a warm pytest process. Build Gate 14 fails in a new shell, because `event_time` round-tripped through JSON as a string. This is not a cosmetic byte difference: `publish_run_record` maps `event_time` straight onto `available_at` (`flow/materialize.py:774-777`), and `_stage_and_publish` runs `validate(...)` then `raise_if_failed()` (`:520-521`, `:527-529`) against a registration declaring `available_at` as the time column. So a JSON round trip makes cold publish **fail validation**, not merely differ in bytes — a sharper and more testable failure.

**Earliest observable signal.** The first cold-process reload where a `recorder_rows` value's `type()` differs from what the recorder appended. Invisible to any test that persists and reloads inside one process.

**Prevented by.** S7 mandates **parquet, not JSON** (`pa.Table.from_pylist` + `pq.write_table(..., compression="zstd")`, the path `materialize.py:505-513` already uses), so `Decimal` and tz-aware `datetime` survive as Arrow types. S14 asserts across a genuine subprocess boundary using the invocation S15 makes exist, and adds the sub-assertion that cold-process `available_at` reads back as a timestamp, not a string.

### Scenario 3 — The skill is installed but never read.

**Narrative.** Build Gate 8–12c all pass. Agent B's framework surfaces the *adapter* — 20 lines of pointer — as the skill body. The agent does not chase the pointer, concludes the skill is a stub, and reads `qlibx/src/`. The Spawn Gate fails on "zero `qlibx/src/` reads" and every downstream friction entry is misattributed to the CLI.

**Earliest observable signal.** The transcript shows the adapter opened with no subsequent open of `.agents/skills/vqapr/SKILL.md`.

**Prevented by.** S11 makes the adapter self-sufficient about its own indirection: a repo-root-relative path stated unambiguously, an explicit imperative to read the target before acting, and trigger-bearing frontmatter so the framework's matcher fires on the adapter. **P3**'s MISSION-A.md makes source-reading auditable and self-reported, converting an unattributable failure into a diagnosed one. Residual risk stays open as R3 with a stated contingency.

## Expanded Test Plan

### Protecting the ~60 existing exact-error-code assertions

One layer carries the weight, and it is mechanically sound. `collector(stage, family)` at `domain/errors.py:178-179` merely constructs `_Collector`, whose `done()` passes `self.stage` through to `Diagnosis`. `code` strings are assembled independently at the 37 `Failure.bounded()` callsites and never pass through `collector()`. Therefore a membership check there **provably cannot rewrite a code**. Combined with S4 raising only on an *unregistered* stage and never normalizing, the registry cannot alter any emitted code.

The real proof is the unchanged re-run of `tests/data/test_scan.py`, `tests/flow/test_preflight.py`, `tests/cli/test_commands.py`, `tests/cli/test_register.py`, `tests/cli/test_envelope.py`, `tests/flow/test_materialize.py`, `tests/flow/test_publish_run_record.py`, `tests/boundaries/test_public.py`.

Pass 1's two extra layers stay **dropped**: a hand-maintained tuple of asserted codes duplicates ~60 existing assertions and will itself drift, and "each constant equals its historical string" is a literal-equals-literal tautology that passes even if no callsite uses the constant — which repo rules forbid.

### Unit

- **New `tests/domain/test_stage_registry.py`** — the **static exhaustiveness test** (Principle 3): import every module under `src/vqapr/`, collect every module-level `*_STAGE` constant, assert each is declared in `descriptors.STAGES`. This is the total check that makes Build Gate 6/7 honest. Plus: `collector()` raises `VqaprError` (not `ValueError`) on an unregistered stage, on a registered meta-stage; `collector()` preserves the stage string verbatim; `FAILURE_STAGES ⊂ STAGES`. **This is also the only place the `FAMILIES`-mirrors-`FailureFamily` correspondence is asserted** — the test may import both `vqapr.descriptors` and `vqapr.domain.errors`, whereas `descriptors` itself must not import the enum (S3, ARCH-16). Enforcement remains `stage`-only, since `family: FailureFamily` is already a closed `StrEnum` and a membership check is redundant with the type.
- **New `tests/agent/test_descriptors.py`** — `vqapr.descriptors` imports without importing `vqapr.agent` **and without importing `vqapr.domain`** (the import-cycle guard, ARCH-16), asserted in a **clean subprocess** that probes `sys.modules` after importing `vqapr.descriptors` — an in-process assertion is guaranteed-red and uninformative once the test session has already imported the package. Follow the existing precedent at `tests/boundaries/test_capability_absence.py:86-103`, whose rationale is stated at `:7-13`; `src/vqapr/__init__.py` is empty, so the probe starts clean (CRIT-17); `len(STAGES) >= 1` (Build Gate 7); `VERBS` equals the 7 final verbs.
- **New `tests/agent/test_manifest.py`** — manifest round-trip; sha256 per generated **and** per source file; source-content change with unchanged version reports stale (12c); modified generated file reported not deleted absent `--force` (12b); installed file set excludes `agent/sample/`.
- **Extend `tests/cli/test_commands.py`** — every subparser has non-empty `description` (3); `--help` lists 7 verbs (2); template output carries all 8 `cli/run.py:33` `_REQUIRED` keys (4).
- **New `tests/flow/test_run_record_io.py`** — persisted rows preserve `Decimal` and tz-aware `datetime` exactly; absent/corrupt manifest fails typed; existing run directory refuses typed, not `OSError`.

### Integration

- **Extend `tests/cli/test_commands.py`** — `list` on an empty dir → `ok:true, count:0` (1), targeting `cli/list_.py:74`. `vqapr run nope.yaml` → `ok:false`, `stage != "unhandled"`, **no `detail`/`traceback`** (5). Template spec → registered stage, code prefixed (6). `vqapr new` re-run and non-mapping/incomplete spec each fail typed.
- **New `tests/cli/test_materialize.py` / `tests/cli/test_publish.py`** — spec-in/envelope-out; missing file, malformed YAML, unknown `run_id` each typed and non-`unhandled`.
- **Extend `tests/cli/test_commands.py`** — `vqapr list runs` enumerates persisted run directories and returns their ids (S8).
- **New `tests/agent/test_skill_install.py`** — dry-run resolves the `.git` root and writes nothing (8); both targets created, adapter ≤20 lines containing `.agents/skills/vqapr` (9); body 80–124 lines with frontmatter (10); `AGENTS.md`/`CLAUDE.md` untouched (11); install→install byte-idempotent; remove leaves the tree clean (12); `references/stages.md` rendered from `descriptors` and disambiguating the two `stage` vocabularies.

### The `materialize` partial-instrument-mismatch case — its first test

Every `materialize()` callsite in `tests/flow/test_materialize.py` passes `instruments=("A","B")` — lines 99, 123, 146, 169, 197, 230, 256. At arity 2 the only reachable outcomes are full match and full mismatch, and full mismatch is already covered by `materialize.output.empty` (893-900). Partial overlap has genuinely never been exercised.

In `tests/flow/test_materialize.py`:

1. **Widen the fixture** to ≥4 instruments so partial overlap is expressible. The existing two-name tests stay untouched as the regression baseline; the fixture is additive.
2. **`test_partial_instrument_mismatch_is_refused`** — request 4, of which 2 exist. Assert `VqaprError` at `_INPUT_STAGE` with code **`materialize.input.instruments_unknown`** (the exact string, fixed here so test and implementation are written against one agreed value — following the existing `f"{_INPUT_STAGE}.instruments_invalid"` convention at `:234`); assert the unknown identities appear in `examples`, bounded by `MAX_EXAMPLES` (5); assert **no artifact written** — neither `.vqapr/materialized/<stem>.parquet` nor `.lineage.json` exists. That last assertion is the actual bug: today it publishes and exits 0.
3. **`test_full_instrument_match_still_publishes`** — the widened fixture with an exact list still succeeds, proving the check is not over-tight.
4. **`test_unknown_evaluation_time_is_refused`** — symmetric case, code `materialize.input.evaluation_times_unknown`.
5. **`test_total_mismatch_still_reports_output_empty`** — pins that the new input-stage check does not shadow the existing code.
6. **`test_from_dataset_without_range_is_refused`** — the unbounded-scan guard has its own test.

### E2E

- **New `tests/cli/test_cold_process_publish.py`** — register → `vqapr materialize` → `vqapr run` (capture `run_id`) → **new subprocess** `vqapr publish <run_id>`, using the S15 entrypoint. The byte comparison follows S7's **persist-once-then-copy** protocol, detailed in S14. Byte-identity **is** achievable without a normalizer: `_lineage_envelope` (`materialize.py:363-386`) emits only `schema_version`, `operation`, `output.{dataset_id,source_id,value_fields}`, and `instruments` — no wall-clock, no absolute path — and the lineage `source_id` is `f"record-{spec.dataset_id}"` (`:794`), which is root-independent.
- Sub-assertion: cold-process `available_at` reads back as a timestamp, not a string.

### Observability

- **`detail` is not a proxy for untypedness.** `cli/envelope.py:96-121` writes `detail` whenever the traceback exceeds `MAX_INLINE_TRACEBACK_LINES` (8, at `:23`) **and** `project_root` is not None, computed from `traceback.format_exception` *before* `as_dict()` is consulted. A typed `VqaprError` raised deep in the stack still emits `detail`. Build Gate 5 therefore cannot be guaranteed by typedness. S10 guarantees it **by mechanism**: the missing-file guard raises shallowly, directly in the CLI handler, so its traceback stays under the threshold. Tests assert on `stage` and on the literal absence of the `detail`/`traceback` keys, never inferring one from the other.
- A test enumerates every stage the CLI can emit — including success stages `workspace.list`, `component.new`, `workspace.register`, `run.complete` and the new materialize/publish success stages — and asserts each is in `descriptors.STAGES`. `cli.usage` and `unhandled` live in the CLI bucket, outside `FAILURE_STAGES`, consistent with `envelope.py:61-62` and `:108-109` deliberately setting `family: None`.

## Work Breakdown

**24 steps**: S1–S15 (15), C1–C4 (4), P1–P5 (5). Lanes: **[R]** registry, **[F]** friction, **[V]** verbs/persistence, **[S]** skill, **[C]** canon+records, **[P]** pre-spawn.

---

**S1 — Lift the inline stage literals** *(lane R, no deps, parallel with S2)*
- Files: `src/vqapr/data/scan.py` — **7 sites, 7 distinct values** (146, 279, 308, 343, 394, 487, 693). `src/vqapr/flow/preflight.py` — **4 sites, 3 distinct values** (188, 215, 278, 304; `preflight.execution` repeats at 215 and 304). Total **11 sites / 10 distinct values** — the spec's "10" is a value count, so an agent lifting "10 sites" misses one.
- Change: module-level `*_STAGE` constants matching the existing convention (`workspace.py:110-123`, `data/datasets.py:19-20`, `flow/materialize.py:36-39`); values character-identical to what they replace.
- Observable: `tests/data/test_scan.py` and `tests/flow/test_preflight.py` pass unchanged; no literal stage string remains in either file.
- Build Gate: precondition for 6, 7. **Pre-spawn task 3.** Parallel: yes.

**S2 — Inventory runtime-parameter stages** *(lane R, no deps, parallel with S1)*
- Files: read-only survey of `workspace.py:776,802,810,878`, `flow/materialize.py:180`, `exchange/execution_table.py:84`.
- Change: enumerate every value those runtime `stage` parameters can take; a registry enforcing at `collector()` sees them at runtime, and they are reachable from user input.
- Observable: a written list, each value traced to its callsite. Feeds S3/S4. Parallel: yes.

**S3 — Create `vqapr.descriptors`** *(lane R, deps: S1, S2)*
- Files: new `src/vqapr/descriptors.py` (top level, per Principle 8).
- Change: declare three named buckets — `FAILURE_STAGES`, `SUCCESS_STAGES`, `CLI_STAGES` — plus `STAGES` as their flat union (Build Gate 7 does membership on `STAGES`; `collector()` checks the `FAILURE_STAGES` subset, so conflating them would let `collector()` admit `workspace.list` as a failure stage). Also `FAMILIES` and `VERBS` (the 7 verbs).
- **Import direction (ARCH-16):** `descriptors` **imports nothing from `vqapr.domain`**, and nothing from `vqapr.agent`. S4 makes `domain/errors.py` import `FAILURE_STAGES` from `descriptors`; if `descriptors` imported `FailureFamily` to build `FAMILIES`, the `from` statement would execute before `FailureFamily` is bound at `domain/errors.py:19-28` and module load would fail. `domain/errors.py:10-13` has no internal imports today, so this cycle does not exist yet and must not be created. **Therefore `FAMILIES` is declared as literal strings**, and the "mirrors `FailureFamily`'s 7 members" correspondence is asserted **only** in `tests/domain/test_stage_registry.py`, which may import both. This is the same discipline Principle 8 applies to `agent/`, extended downward to `domain/`.
- **Decision: `descriptors` is NOT added to `public.py`'s `__all__`** — `tests/boundaries/test_public.py:181-322` asserts exact tuple equality over 105 names, so adding it turns that test red for no gate benefit; it is imported as `vqapr.descriptors` directly, exactly as Build Gate 7 writes it.
- Observable: `python -c "import vqapr.descriptors as d; print(len(d.STAGES))"` → ≥1; the import-direction test passes. **Build Gate 7 (first half).** Must land before S4.

**S4 — Registry enforcement: static test + typed runtime guard** *(lane R, dep: S3)*
- Files: `src/vqapr/domain/errors.py:178-179`; new `tests/domain/test_stage_registry.py`.
- Change: (i) the **static exhaustiveness test** is the coverage mechanism (Principle 3). (ii) `collector()` validates `stage ∈ FAILURE_STAGES` and raises **`VqaprError` on a registered meta-stage** — never a bare `ValueError`, which `cli/main.py:67-70` would convert to `stage:"unhandled"`, re-creating the exact defect that moving validation out of `Failure.__post_init__` prevents (Principle 2). Constructing `VqaprError` does not re-enter `collector()`, so there is no recursion hazard. Enforcement is **`stage`-only**. Never added to `Failure.__post_init__`.
- Observable: full suite green; static test passes over all modules; `collector("not.a.stage")` raises `VqaprError` with a registered stage and no traceback escape. **Build Gate 6, 7 (second half).** See IR-1.

**S5 — Friction fixes (a) and (c)** *(lane F, no deps, parallel with all of lane R)*
- Files: `src/vqapr/cli/list_.py:74`; `src/vqapr/cli/main.py:52-53` and each verb module's `add_arguments`.
- Change: (a) `list` on a workspace-less directory returns `ok:true, count:0, items:[]` — guard the `Workspace.open` call, do not catch broadly. (c) every `add_parser(name)` gains `help=`/`description=`; per-argument help added.
- Observable: `mkdir t && cd t && vqapr list datasets` → `ok:true, stage:"workspace.list", count:0`, exit 0; all 7 verbs print a non-empty `--help` description. **Build Gate 1, 2, 3.** Parallel: yes.

**S6 — Materialize input schema + membership check** *(lane V, deps: S3, S4)*
- Files: `src/vqapr/flow/materialize.py` — a **new third call sited after `Workspace.open` at line 837**, not inside `_evaluation_times`/`_instruments`. Those run at 835-836, *before* the workspace opens, and receive no `project_root`, `Workspace`, or `dataset_id`, so they structurally cannot consult `Workspace.instruments()`/`evaluation_times()`.
- Change (schema): the materialize YAML requires explicit bounds; there is **no implicit "all"**. `instruments:` accepts either `explicit: [...]` or `from_dataset: <source dataset_id>`; `evaluation_times:` accepts either `explicit: [...]` or `from_dataset:` **with mandatory `start:` and `end:`**. A bare `from_dataset` without a range is refused at the input stage — this prevents the 4,962 × ~11-year cross product while letting an agent say "the whole universe for this quarter" without transcribing 4,962 tickers, which is Pre-Mortem 1's actual failure mode.
- Change (check): `_require_membership(workspace, spec.dataset_id, times, selected_instruments)` raises `_INPUT_STAGE` with codes `materialize.input.instruments_unknown` / `materialize.input.evaluation_times_unknown`, unknown identities in `examples` bounded by `MAX_EXAMPLES` (5), running before `workspace.component(...)` so nothing is published.
- **Cost decision (CRIT-16 — restated honestly; the pass-2 "zero additional scans" claim was wrong).** `Workspace.instruments()` (`workspace.py:302-316`) and `evaluation_times()` (`:318-338`) each run a fresh `scan.distinct_values` `SELECT DISTINCT … ORDER BY` full-column scan, with **no memoization**. Because `materialize()` receives already-concrete sequences, the `from_dataset` expansion necessarily happens in the S9 CLI verb while this check runs inside `flow/materialize.py` after `:837` — opposite sides of an API boundary, so the two cannot share one result. **The honest cost is therefore up to 4 scans per `materialize` on the `from_dataset` path, and 2 when both `instruments` and `evaluation_times` are explicit.** We accept that cost rather than memoizing on `Workspace` or relocating the check, because keeping the check inside the flow is what protects direct `public.py` callers who bypass the CLI entirely — the safety property is worth more than two scans. **Cross-reference R7:** this roughly doubles the scan cost the 30-minute Build Gate budget must absorb, which is one more reason to time rungs 1–3 during P1/P2.
- Observable: the six `test_materialize.py` tests; existing two-name tests unchanged; total mismatch still yields `materialize.output.empty`. Precondition for 13. Retires Pre-Mortem 1.

**S7 — The `.vqapr/runs/<id>/` contract** *(lane V, no code deps — start at t0 alongside S1)*
- Files: design artifact; consumed by S8, S9, S14.
- **`run_id` = `FrozenRun.identity`** (`flow/run.py:373-378`), not minted. It is already a sha256 over every frozen declaration and already the `run_id` column on every recorder row. Pass 1's worry that "two identical runs collide" is not a collision but the correct answer: identical frozen declarations *are* the same run. Refuse-on-existing is then consistent with `_stage_and_publish` rather than a new convention.
- **Layout:** `.vqapr/runs/<run_id>/manifest.json` (`schema_version`, `run_id`, `package_version`, `created_at`, `finalization{…}`, `tables[{table_id, row_count, sha256}]`); `tables/<safe_table_id>.parquet` one file per recorder table; `publish-spec.yaml` (see S9).
- **Encoding: parquet, mandatory — not JSON.** `pa.Table.from_pylist` + `pq.write_table(..., compression="zstd")`, the path `materialize.py:505-513` already uses, so `Decimal` and tz-aware `datetime` survive as Arrow types. JSON degrades `event_time` to a string, which `publish_run_record` maps onto `available_at` (`:774-777`) and the shared authority re-validates as a timestamp (`:520-521`, `:527-529`) — so JSON makes cold publish *fail validation*, not merely differ in bytes.
- **Durability:** stage into `.vqapr/runs/.<run_id>.tmp-<pid>/`, fsync each file, `os.replace` the directory into place, reusing `WORKSPACE_SWAP_ATTEMPTS`/`WORKSPACE_SWAP_BACKOFF` (`workspace.py:63-64,1028-1037`). **No workspace lock** — the path is unique per run and never read-modify-written (Principle 6). Refusal on an existing run directory is a **typed** failure, not an `OSError`.
- **Byte-comparison protocol — persist once, then copy (ARCH-17, CRIT-15).** The run is executed and persisted **exactly once, in root A**. Root B does **not** re-run: it receives `.vqapr/runs/<run_id>/` by directory copy and publishes from that copy. Re-running in root B is **forbidden**, because `run_id` is path-dependent — `cli/register.py:137-139` resolves a relative source path against the declaration's own directory, and `FrozenRun._derive_identity` includes `str(source.path)` for both sources and the execution input (`flow/run.py:404-405,492-495`). Two independently seeded roots therefore produce **different** `run_id` values from byte-identical declarations, and that difference is not cosmetic: `run_id` is one of the five mandatory `FLOW_ENVELOPE_FIELDS` stamped on every row (`evidence/recorder.py:77`, `evidence/tables.py:8`) and is the source of the lineage `payload["record"]["run_identity"]` (`materialize.py:805`), so both the parquet and the lineage JSON would differ. **Root B's required initial state:** an initialized workspace that opens successfully (`publish_run_record` calls `Workspace.open(project)` at `materialize.py:741` before all other work) and that does **not** already register `dataset_id` (`:532` registers it; `:838-846` refuses a duplicate at the input stage). Byte-identity needs no normalizer: `_lineage_envelope` (`:363-386`) carries no wall-clock and no absolute path, and the lineage `source_id` is `f"record-{spec.dataset_id}"` (`:794`), which is root-independent.
- **Growth/cleanup:** out of scope this cycle; `manifest.json` carries `created_at` so a later sweeper has a key.
- Observable: a written contract sufficient for S8/S9/S14 to proceed independently. Precondition for 13, 14.

**S8 — `run` persists narrowly, surfaces and lists `run_id`** *(lane V, deps: S4, S7)*
- Files: `src/vqapr/cli/run.py:177-181`; new run-record I/O module under `src/vqapr/flow/`; `src/vqapr/cli/list_.py`.
- Change: after `execute_run`, write the S7 layout. Envelope becomes `success("run.complete", run_id=frozen.identity, occurrences=…, account_version=…)` — `frozen` is already in scope at `cli/run.py:176`, so this is the only change Build Gate 13's `run_id` requirement needs.
- **`list runs` mechanism (ARCH-18).** `runs` is added to `KINDS` but **must be handled *before* the `_ACCESSORS` lookup**, not as an `_ACCESSORS` entry. `cli/list_.py:75` dispatches `getattr(workspace, _ACCESSORS[args.kind])`, so every accessor entry must name a `Workspace` property; the eight existing kinds all do, and runs live on disk under `.vqapr/runs/` with no corresponding property — an `_ACCESSORS` entry would raise `AttributeError`. Instead, branch on `runs` first and enumerate `.vqapr/runs/*/manifest.json`, summarizing `run_id`, `created_at`, and `tables`. Keep the same `success("workspace.list", …)` envelope shape so the verb stays uniform. Rationale unchanged: Build Gate 14 requires using the id in a *new shell*, and today it is emitted once and then undiscoverable.
- Observable: `vqapr run spec.yaml` → `ok:true` with `run_id`; `.vqapr/runs/<run_id>/` holds the contracted files; `vqapr list runs` returns the id; `tests/flow/test_run_record_io.py` green. **Build Gate 13** (partial).

**S9 — `materialize` and `publish` verbs** *(lane V, deps: S6, S8)*
- Files: new `src/vqapr/cli/materialize.py`, new `src/vqapr/cli/publish.py`; `src/vqapr/cli/main.py:19-24`.
- **Surface decision:** `publish` takes a **positional `<run_id>`** with an optional `--spec PATH` override. This makes Build Gate 14 literally true while honouring the spec's YAML-input constraint, because **`run` writes the publish spec at persist time** — `vqapr publish <run_id>` means "use the spec this run already wrote".
- **`RunRecordSpec` source:** `.vqapr/runs/<run_id>/publish-spec.yaml` carries `run_id`, `table_id`, `dataset_id`, `value_fields`. `table_id` and the declared fields come from `RecorderManifest` (`evidence/recorder.py:16-19,96-99`); `value_fields` must include all five `FLOW_ENVELOPE_FIELDS` — `run_id`, `producer_id`, `stage`, `event_time`, `sequence` (`evidence/tables.py:8`) — because `RunRecordSpec.of` rejects the spec without them. **`dataset_id` is the one field the user must choose** and fails typed when absent, so `constraint:skill-never-bypasses` holds: nothing is inferred.
- **Carrier object:** `publish_run_record` reaches through `getattr(getattr(result, "final_state", None), "recorder_rows", None)` at `:745` and looks rows up via `recorded.get(spec.table_id, ())` at `:754`. A cold process holds no `SimulationResult` by Principle 5, so `publish` constructs a minimal carrier exposing exactly `.final_state.recorder_rows` as `Mapping[str, tuple[Mapping[str, object], ...]]`, rebuilt from the parquet tables.
- `materialize` performs the `from_dataset` expansion described in S6 before calling the flow. Both verbs guard the spec path **before** `read_text` (Principle 1). Registered in `_COMMANDS` with help/description per S5.
- Observable: `--help` lists 7 verbs; both round-trip a spec; unknown `run_id` fails typed. **Build Gate 2, 13, 14.**

**S10 — Friction fixes (b) and (d)** *(lane F, deps: S4, S9)*
- Files: `src/vqapr/cli/run.py:170-174`, `src/vqapr/cli/new.py:69-71`, the two new verbs; template emitter in `cli/new.py`.
- Change (b): a missing input file yields a typed registered stage, raised **shallowly in the CLI handler** so the traceback stays under `MAX_INLINE_TRACEBACK_LINES` and no `detail` key is written. Widened to `cli/new.py:69-71` (bare `FileExistsError` on re-run) and `cli/run.py:171-174` (bare `TypeError`/`ValueError` for a non-mapping or incomplete spec) — all become `unhandled` today. Rung 2 uses `new` and the Spawn Gate allows 3 tries per rung, so a retry hits exactly this. All three become typed.
- Change (d): a template emitter for declaration YAML, run-spec YAML, materialize-spec YAML.
- **R4 resolution:** the emitter writes the template **to a file** and returns the normal one-line envelope carrying the path; it does **not** write YAML to stdout. Build Gate 4's `vqapr new run-spec > spec.yaml` is amended to `vqapr new run-spec --out spec.yaml`, because writing raw YAML to stdout would break `envelope.py`'s guarantee that stdout is exactly one JSON line. See IR-2.
- Observable: `vqapr run nope.yaml` → `ok:false`, `stage != "unhandled"`, **no `detail`/`traceback` key**; re-running `vqapr new` fails typed; the emitted run-spec carries all 8 `_REQUIRED` keys; running it yields a registered stage with a prefixed code. **Build Gate 4, 5, 6.**

**S11 — Skill content: `SKILL.md` + adapter + references** *(lane S, dep: S3; parallel with lane V)*
- Files: new `src/vqapr/agent/skill/SKILL.md`; adapter template; `references/` sources.
- Change: body carries when-to-use plus the 3-rung path only, 80–124 lines, frontmatter `name`+`description`, zero verb detail in prose. Adapter ≤20 lines containing `.agents/skills/vqapr`, with frontmatter, an unambiguous path, and an explicit imperative to read the target before acting (Pre-Mortem 3). `references/stages.md` is rendered from `descriptors` at install time and **must disambiguate the two `stage` vocabularies**: `descriptors.STAGES` holds failure/CLI stages (`materialize.input`, `workspace.list`), while the recorder's `stage` column holds `OperationRole` values (`STRATEGY_CALLBACK`/`VALUATION`/`MONITORING`) — and `VALUATION` exists in both `FailureFamily` and `OperationRole` with different meanings (`evidence/tables.py:8`, `flow/simulation.py:1516`, `runtime/agendas.py:26-29`, `domain/errors.py:19-28`). Unlabelled, an agent will conflate them.
- Observable: 80–124 lines; `head -1` is `---`; both frontmatter keys present. **Build Gate 9, 10.**

**S12 — `vqapr skill install|remove|list`** *(lane S, deps: S3, S11)*
- Files: new `src/vqapr/agent/targets.py`, new `src/vqapr/cli/skill.py`; `cli/main.py` `_COMMANDS`.
- Change: `--target codex|claude|both` (default both); root auto-detected by walking to the `.git` root, `--into DIR` overrides, `--dry-run` prints the resolved path and writes nothing. Full text to `<root>/.agents/skills/vqapr/`, adapter to `<root>/.claude/skills/vqapr-skill/SKILL.md`. Manifest `.vqapr-skill.json` records package version, install timestamp, sha256 per generated file **and** per source skill file. `remove` deletes only sha-matching files and reports the rest; `--force` deletes modified files. Never reads or writes `AGENTS.md`/`CLAUDE.md`. Renders `references/stages.md`.
- **Installed file set:** ships **only `agent/skill/` content**; never `agent/sample/` sources, which are a pre-existing package concern (Principle 7). Manifest sha tracking covers skill files only. The manifest JSON schema is written out as part of this step.
- Observable: **Build Gate 8, 9, 11, 12, 12b, 12c**; `git status --porcelain AGENTS.md CLAUDE.md` empty; repeat install byte-idempotent.

**S13 — Test build-out** *(lanes R/V/S, deps: the step each test covers; internally parallel)*
- Files: as enumerated in the Expanded Test Plan.
- Change: land tests alongside their steps, not in a trailing batch.
- Observable: each new test fails before its step and passes after.

**S14 — Cold-process E2E** *(lane V, deps: S9, S10, S15)*
- Files: new `tests/cli/test_cold_process_publish.py`.
- Change: the rung 1–3 chain across a real subprocess boundary, using the S15 entrypoint. **Persist once in root A, copy the run directory into root B, publish from the copy** — the S7 protocol, restated here so an implementer reading only this step builds the correct test:
  1. Seed root A, register, materialize, and `vqapr run` **once**. Capture `run_id` from the envelope.
  2. Publish in-process in root A for `dataset_id`.
  3. Prepare root B: an initialized workspace that opens successfully and does **not** already register `dataset_id` (CRIT-15).
  4. **Copy** `.vqapr/runs/<run_id>/` from root A into root B. Do **not** re-run in root B — `run_id` is path-dependent and a re-run yields a different id, which propagates into both the published parquet (it is a mandatory envelope value field) and the lineage `run_identity`, failing the comparison for reasons unrelated to cold-process fidelity (ARCH-17).
  5. In a **new subprocess**, `vqapr publish <run_id>` in root B for the same `dataset_id`.
  6. Compare the two `.parquet` + `.lineage.json` pairs byte-for-byte. Two roots are required because `_stage_and_publish` raises `<publish>.path_exists` when either path already exists (`materialize.py:464-474`), and changing `dataset_id` to dodge it would change `stem` and the lineage `output.dataset_id`, defeating the comparison.
- Sub-assertion: cold-process `available_at` reads back as a timestamp, not a string.
- Observable: **Build Gate 14** — the dominating item. Retires Pre-Mortem 2.

**S15 — Add `src/vqapr/__main__.py`** *(lane V, no deps, parallel)*
- Files: new `src/vqapr/__main__.py`.
- Change: `python -m vqapr` does not work today — the file does not exist and `pyproject.toml [project.scripts]` declares only `vqapr = "vqapr.cli:main"`. Add the module so the E2E subprocess invocation is deterministic and independent of PATH/venv console-script resolution, which is fragile on Windows inside a test.
- Observable: `python -m vqapr --help` returns the same envelope as `vqapr --help`. Precondition for S14 / Build Gate 14. Parallel: yes.

**C1 — Canon edit (i): `cli/main.py` docstring usage/remedy split** *(lane C, dep: S5; record 047)*
- Files: `src/vqapr/cli/main.py` docstring; new `docs/implementations/047-<slug>.md`.
- Change: amend the docstring so the CLI owns *usage* text while the skill owns *remedy*, dissolving the cycle. Rides inside the record for S5's behavioural change, per `AGENTS.md`.
- Observable: record 047 exists; the docstring no longer forbids what S5 does. **Build Gate 3** (makes it legitimate rather than contradictory).

**C2 — Canon edit (ii): PRD §2.6 same split** *(lane C, dep: S5; record 048)*
- Files: `docs/vqapr-prd.md` §2.6; new `docs/implementations/048-<slug>.md`.
- Change: the same authority split in canon. Split from C1 because the spec requires four edits with a record *each* (Round 13: "네 건 전부 + 각각 구현 기록").
- Observable: §2.6 states the split; record 048 exists.

**C3 — Canon edit (iii): the two agent READMEs** *(lane C, dep: S12; record 049)*
- Files: `src/vqapr/agent/skill/README.md`, `src/vqapr/agent/sample/README.md`, new `docs/implementations/049-<slug>.md`.
- Change: drop present-tense claims about unbuilt commands, name the real verb. `agent/skill/README.md` opens with "`vqapr agent install`이 이 디렉터리의 내용을 …복사한다" — present tense for a command that does not exist, which is the literal root cause of FRICTION F-001. Renaming the verb without fixing the prose reproduces it verbatim.
- Observable: neither README references `vqapr agent install`; both name `vqapr skill install`; record 049 exists.

**C4 — Canon edit (iv): architecture + the wider drift it exposes** *(lane C, dep: S4; record 050)*
- Files: `docs/vqapr-architecture.md` §10.4 **and** the layout tree at `:2752-2757` **and** §13 step 2; `docs/vqapr-prd.md` §11.3; new `docs/implementations/050-<slug>.md`.
- Change: narrow §10.4's descriptors claim to stage/family — "generate from source so drift is structurally impossible" is false for reason codes, which are f-string-assembled across 37 callsites and whose enumeration is an explicit non-goal. The layout tree places `descriptors.py` *inside* `agent/` and names an `onboarding.py` with preview/apply/update/remove; §13 step 2 repeats `agent/descriptors`; PRD §11.3 still describes the old verb set. Principle 8 puts descriptors at top level, so the docs that say otherwise must move with it.
- Observable: §10.4 claims stage/family only; the layout tree shows top-level `descriptors.py`; §13 step 2 and PRD §11.3 match the shipped surface; record 050 exists.

*(Records 047–050 are the next four unused numbers; 046 is the highest present. Records are per behavioural change and canon edits ride inside them. Allocate the next unused number at landing time if a lane lands out of order; never renumber.)*

**P1 — Freeze the rung-1 source numbers** *(lane P, no deps, fully parallel)*
- Change: measure and freeze `adjusted_prices.parquet` row count, date range, instrument count (≈2015-01-02→2026-07-20, 4,962 instruments, dividends excluded). **Pre-spawn task 1.**

**P2 — Freeze the rung-2 coverage target** *(lane P, dep: S6)*
- Change: compute and freeze the target (date, instrument) coverage ratio. Also time rungs 1–3 against R7's budget, given S6's honest scan cost. **Pre-spawn task 2.**

**P3 — Write `MISSION-A.md`** *(lane P, dep: S11)*
- Change: rung-1 stop condition, source-reading prohibition, mandatory friction logging, explicit halt criteria. `MISSION-B.md` stays deferred until Agent A's friction log exists. This is the step Pre-Mortem 3 and R3 depend on. **Pre-spawn task 4.**

**P4 — Add `wrong` severity to FRICTION.md** *(lane P, no deps, parallel)*
- Change: introduce `wrong` so a silently incorrect result is recordable at all. **Spawn Gate criterion.**

**P5 — Build Gate dry run** *(deps: everything)*
- Change: execute the **16** Build Gate items in an empty directory, in a fresh shell, within 30 minutes, reading no source.
- **Authoritative enumeration:** items **1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 12b, 12c, 13, 14** = 16 checkboxes. The spec's Ontology row says 14; the checklist is authoritative at **16**, and 16/16 is the pass condition.
- Observable: 16/16. Only then is a spawn worth its cost (D3).

---

**Parallelism summary.** At t0: lane **R** (S1/S2 → S3 → S4), lane **F** (S5), lane **V**'s design-only S7 and the independent S15, and **P1/P4**. Lane **V** proper (S6 → S8 → S9 → S10 → S14) opens after S4 and S7. Lane **S** (S11 → S12) needs only S3 and runs parallel to all of lane V. Lane **C** trails its behavioural step. S13 is distributed. P2 follows S6; P3 follows S11; P5 is last.

## Risks and Open Questions

**R1 — Materialize input schema.** *Resolved.* S6 fixes the schema: explicit bounds required, `from_dataset` sanctioned only with a mandatory date range, no implicit "all". Residual: whether `evaluation_times.from_dataset` should intersect with a trading calendar rather than the raw distinct set. Low impact — the range bound already caps cost.

**R2 — Runs-directory contract.** *Resolved.* `run_id = FrozenRun.identity`; parquet encoding; persist-once-then-copy byte comparison; typed refuse-on-existing; `created_at` for a future sweeper. Residual: retention/cleanup is explicitly out of scope, so `.vqapr/runs/` grows unbounded within a project. Acceptable this cycle; named so it is not rediscovered as a defect.

**R3 — Will a reading agent follow the `.claude/` adapter?** *(evidentially thin; unchanged)* The adapter rests on the measurement that kaist-thesis already runs both targets and that two copies of existing skills have drifted to different shas — which justifies single-source but does not establish that an indirection is *followed*. Build Gate 9 asserts only shape, not behaviour; it is the one gate item whose passing does not entail its intent. Mitigations in **S11**; auditability via **P3**. **Contingency: if Agent A's transcript shows the adapter opened without follow-through, ship full text to both targets and accept sha drift before spawning B.**

**R4 — Template emitter vs the one-JSON-line envelope.** *Resolved* via `--out` (S10). Flagged as **IR-2** because it amends the literal text of Build Gate item 4.

**R5 — CLI/success stages outside the failure registry.** Handled by S3's three buckets with `STAGES` as the flat union. Build Gate 7 does membership on `STAGES` (it checks the *success* stage `workspace.list`), while `collector()` checks `FAILURE_STAGES`. Conflating them would let `collector()` admit `workspace.list` as a failure stage. Low risk, silent trap, mechanically prevented.

**R6 — Reason-code drift stays unguarded, by decision.** The registry narrows to stage/family; reason suffixes stay free-form across 37 f-string callsites. A known limitation per the spec. No action.

**R7 — The 30-minute Build Gate budget is asserted, not measured.** 16 items including two full mission-ladder runs on a 4,962-instrument dataset, plus S6's membership scans — **up to 4 full-column scans per `materialize` on the `from_dataset` path**, which roughly doubles what pass 2 optimistically assumed (see S6's cost decision). Recommend timing rungs 1–3 during P1/P2 and, if over budget, cutting the *gate's* dataset to a bounded slice while keeping the *spawn* on full data.

**R8 — Editable-install staleness is detected, not repaired.** Build Gate 12c reports stale; nothing re-installs. An agent seeing `stale:true` needs to know the remedy is re-running `vqapr skill install`. Recommend `skill list` carry that one line — it is *usage* under the C1/C2 split, so the CLI may own it.

**R9 — `agent/sample/` is exempted, not reconciled.** Principle 7 scopes the import boundary to the new surface and records `agent/sample/` as a pre-existing exemption, because it is tracked, tested (`tests/agent/test_sample_panel.py`), and outside this cycle. Consequence: no repo-wide boundary test can be written this cycle, so the constraint is enforced by review rather than by test for the new files. A future cycle should either migrate `agent/sample/` or formalize a two-tier boundary. Named, not silently fixed.

**R10 — Static exhaustiveness depends on a naming convention.** S4's coverage test discovers stages by scanning for module-level `*_STAGE` constants. A stage introduced under a different name, or held only in a runtime parameter (the `workspace.py:776,802,810,878` class S2 inventories), escapes the static net and is caught only if it happens to flow through `collector()`. This is why the runtime guard is retained as a supplement rather than dropped. Residual gap: a runtime-parameter stage on a non-`collector()` path is unguarded by either mechanism.

**R11 — The two roots must not diverge in any field the lineage carries.** *(rewritten this pass — ARCH-17)* S14 compares artifacts across two project roots under the persist-once-then-copy protocol, so the run itself is executed exactly once and `run_id` is identical by construction. What remains is that root B must not perturb any field `_lineage_envelope` emits — `dataset_id`, `source_id`, `value_fields`, `instruments` — so the publish in root B must use the same `dataset_id` and the same `publish-spec.yaml` copied with the run directory. **Explicitly forbidden: re-running the run in root B**, which would mint a different path-dependent `run_id` and break the comparison for reasons unrelated to cold-process fidelity. Pass 2's "build both roots from one fixture factory" prescribed exactly that and was wrong.

## Sequencing Verdict

Open four fronts at t0. The registry lane leads — lift the 11 literal sites carrying 10 distinct values in `scan.py` and `preflight.py` (S1), inventory the runtime-parameter stages (S2), declare `vqapr.descriptors` at package top level with three buckets and no `vqapr.domain` imports (S3), then land the static exhaustiveness test plus the typed `collector()` guard (S4) — because the registry must be *declared* before `materialize` and `publish` mint new stage strings, which is a declaration-ordering argument rather than the blast-radius one pass 1 gave. In parallel run the two independent friction fixes (S5), the trivially independent `__main__.py` (S15), the now fully-specified runs-directory contract as design work (S7), and the measurement tasks (P1, P4). Once S4 and S7 land, the verb lane runs S6 → S8 → S9 → S10 → S14 while the skill lane runs S11 → S12 independently. Canon edits trail their behavioural steps as records 047–050. Finish with the 16-item Build Gate dry run (P5) before spending a spawn.

**The single step that most retires risk: S14 — the cold-process E2E.** It is the executable form of Build Gate 14, and its precondition chain transitively asserts the template emitter (4), the registry (6/7), all three rungs (13), and the process boundary. It is the only step that can catch Pre-Mortem 2, because type degradation in persisted `recorder_rows` is invisible to every test that stays inside one process. Its two pass-1 mechanical blockers are owned by S15 and S7, and its comparison protocol is now unambiguous: persist once, copy, publish cold, compare.

## Intent Reconciliation Candidates

Points where this plan **refines a mechanism the approved spec asserted**. Intent is preserved in every case; the mechanism changes because the source contradicts the assumed one. **Unchanged from pass 2 — none of this pass's five errata altered an IR's wording.** These go to the user, not to another planning pass.

**IR-1 — `collector()` entry enforcement is the runtime guard, not the coverage mechanism.**
The spec settled (Round 11, N1) that the stage/family registry is "enforced at `collector()` entry ONLY", with the explicit and correct rationale that validation inside `Failure.__post_init__` would flip a typed failure into an `unhandled` traceback. **That placement decision is preserved exactly.** What this plan adds is the finding that `collector(` is called at only 6 sites in 3 files, and that every stage the Build Gate exercises — `workspace.open.missing`, `preflight.*`, `materialize.*` — constructs `VqaprError` directly and bypasses it. So `collector()` validation alone cannot make Build Gate 6/7 true. The plan adds a **static exhaustiveness test** as the coverage mechanism and keeps `collector()` as the runtime supplement. Additionally, `collector()` must raise `VqaprError` on a registered meta-stage rather than a bare `ValueError`, because `cli/main.py:67-70` catches `Exception` and would produce `stage:"unhandled"`, re-creating at the CLI boundary the exact defect the spec's placement decision was designed to prevent. **Confirm:** the user intended `collector()` as the drift barrier; this makes the barrier actually hold, and does not move validation back into `Failure`.

**IR-2 — Build Gate item 4's redirect becomes `--out`.**
The spec writes item 4 as `vqapr new run-spec > spec.yaml`. Writing raw YAML to stdout collides with `envelope.py`'s guarantee that stdout is exactly one JSON line — the single contract the entire agent-facing design rests on, and the one `UsageError` exists to protect. The plan keeps the template emitter and the 8-key requirement intact but changes the invocation to `vqapr new run-spec --out spec.yaml`. **Confirm:** the intent (a template emitter that produces a complete run spec) is fully preserved; only the transport changes.

**IR-3 — `publish` takes a positional `<run_id>`, with the YAML spec written by `run`.**
The spec states `materialize` and `publish` both take a YAML spec file "like `register`/`run`", while Build Gate 14 writes `vqapr publish <run_id>`. These are two different surfaces. The plan satisfies both by having `run` write `publish-spec.yaml` into the run directory at persist time, so the positional id resolves to a YAML spec. `dataset_id` remains user-chosen and fails typed when absent. **Confirm:** this preserves "input is a YAML spec" while making Build Gate 14 literally executable.

**IR-4 — The `agent/` import boundary is scoped to the new surface; `agent/sample/` is exempt.**
The spec's Technical Context states `src/vqapr/agent/` holds "an empty `__init__.py` plus `skill/README.md` and `sample/README.md` only". The repository contradicts this: 7 tracked files including 4 Python modules that import `vqapr.public` and `vqapr.extension.fingerprint`, plus a live test importing them. `constraint:no-import` cannot be enforced repo-wide without deleting or migrating tracked, tested source that no step authorizes touching. The plan scopes the constraint to new files and records the exemption. **Confirm:** the alternative is a new step owning the `agent/sample/` migration, which would expand scope beyond the spec. Both reviewers flag this as the IR deserving the closest attention, because it converts a stated constraint into a review-enforced one (R9 says so plainly).

**IR-5 — Four canon edits produce four records (047–050), and edit (iv) widens.**
The spec requires "canon 수정 4건과 각각의 구현 기록". Edits (i) and (ii) are split into records 047 and 048. Separately, edit (iv) widens beyond §10.4 to the architecture layout tree (`:2752-2757`), §13 step 2, and PRD §11.3, all of which place `descriptors.py` inside `agent/` or describe the old verb set. **Confirm:** the widening is drift correction for the same decision, not new scope — but it does touch two sections the spec did not enumerate.

## Revision Log

### pass 1 → pass 2 (29 findings: 15 Architect, 14 Critic — all accepted, 0 rejected)

**Architect.** ARCH-01 (coverage → static exhaustiveness test; Principle 3, S4, D1 rationale corrected; IR-1; new R10). ARCH-02 (`collector()` raises `VqaprError`; generalized into Principle 2). ARCH-03 (`publish-spec.yaml` written by `run`; IR-3). ARCH-04 (`run_id = FrozenRun.identity`; Principle 5, S7 rewritten; R2 downgraded). ARCH-05 (two project roots; **completed this pass — see ARCH-17**). ARCH-06 (membership check re-sited after `Workspace.open` at `:837`). ARCH-07 (S7 durability: staging dir, fsync, swap retry, typed refuse-on-existing, `created_at`; Principle 6). ARCH-08 (`list runs` added; **mechanism corrected this pass — see ARCH-18**). ARCH-09 (Principle 7 rescoped; IR-4; R9). ARCH-10 (C4 widened to layout tree, §13 step 2, PRD §11.3; Principle 8). ARCH-11 (S6 literal YAML schema; R1 resolved). ARCH-12 (S11 disambiguates the two `stage` vocabularies). ARCH-13 (S10 widened to `new.py` and spec-shape raises). ARCH-14 (16 items enumerated). ARCH-15 (S17 → P3).

**Critic.** CRIT-01 (Principle 7 exemption; IR-4). CRIT-02 (new step S15). CRIT-03 (two-root comparison). CRIT-04 (one publish surface; IR-3). CRIT-05 (carrier object + publish YAML keys). CRIT-06 (16 items). CRIT-07 (S17 → P3). CRIT-08 (four records C1–C4). CRIT-09 (Observability claim retracted; S10 shallow-raise mechanism). CRIT-10 (S6 cost decision recorded; **arithmetic corrected this pass — see CRIT-16**). CRIT-11 (S1 sites vs values split). CRIT-12 (tautology test layers dropped). CRIT-13 (`stage`-only enforcement). CRIT-14 (installed set excludes `agent/sample/`).

### pass 2 → pass 3 (5 findings + 1 partial — all accepted, 0 rejected)

| id | sev | target | disposition |
|---|---|---|---|
| **ARCH-05** | P1 (pass 1) | S7/S14 | **Partial → resolved.** The instruction ("two project roots, same `dataset_id`, same persisted run") was already correct; only R11's elaboration contradicted it. Closed by the ARCH-17 rewrite below. The Architect independently re-verified the supporting claim that byte-identity needs no normalizer: `_lineage_envelope` (`materialize.py:363-386`) emits only `schema_version`, `operation`, `output.{dataset_id,source_id,value_fields}`, `instruments` — no wall-clock, no path. That verification is now cited in the Test Plan's E2E section and in S7. |
| **ARCH-16** | P2 | S3 | **Accepted.** S3 now states that `vqapr.descriptors` **imports nothing from `vqapr.domain`**, declares `FAMILIES` as literal strings, and defers the `FAMILIES`-mirrors-`FailureFamily` correspondence to `tests/domain/test_stage_registry.py`, which may import both. Rationale recorded inline: `domain/errors.py:10-13` has no internal imports today and `FailureFamily` is defined at `:19-28`, so S4's `from descriptors import FAILURE_STAGES` plus a reverse import would fail at module load. Principle 8 generalized from "descriptors sits at top level" to "registry modules sit below their consumers and import nothing from them". A guard assertion is added to `tests/agent/test_descriptors.py`. Must land before S4. |
| **ARCH-17** | P2 | S14 / R11 / S7 | **Accepted.** R11 is rewritten end to end: the fixture-factory framing is removed and replaced with **persist once in root A, copy `.vqapr/runs/<run_id>/` into root B, publish from the copy; re-running in root B is forbidden**. The same protocol is now stated identically in three places — S7's byte-comparison paragraph, S14's six numbered steps, and R11 — so all three agree. Rationale recorded with evidence: `run_id` is path-dependent via `cli/register.py:137-139` and `FrozenRun._derive_identity`'s `sources` block (`flow/run.py:404-405,492-495`), and it propagates into the published parquet as a mandatory `FLOW_ENVELOPE_FIELDS` member (`evidence/recorder.py:77`, `evidence/tables.py:8`) and into the lineage `run_identity` (`materialize.py:805`). R11's residual is restated as what it actually is: the two roots must not diverge in any field the lineage carries. |
| **ARCH-18** | P3 | S8 | **Accepted.** S8 no longer says "add `runs` to `_ACCESSORS`" — pass 2 adopted that pass-1 wording verbatim and it is wrong. `runs` is now specified as a kind handled **before** the accessor lookup, enumerating `.vqapr/runs/*/manifest.json` and summarizing `run_id`, `created_at`, `tables`, while keeping the `success("workspace.list", …)` envelope shape. Rationale recorded: `cli/list_.py:75` dispatches `getattr(workspace, _ACCESSORS[args.kind])`, all eight existing kinds name a `Workspace` property, and runs live on disk, so an `_ACCESSORS` entry would raise `AttributeError`. |
| **CRIT-15** | P3 | S14 | **Accepted.** Root B's required initial state is now stated in both S7's byte-comparison paragraph and S14 step 3: an initialized workspace that opens successfully and does **not** already register `dataset_id`. Evidence cited: `publish_run_record` calls `Workspace.open(project)` at `materialize.py:741` before all other work, `:532` registers the dataset, and `:466-474` refuses an existing parquet or lineage path (`path_exists`). (Corrected at landing per ARCH-20: `:838-846` is the duplicate-`dataset_id` guard inside `materialize()`, not inside `publish_run_record()`, which has no `dataset_exists` check across `:717-819`. The requirement is unchanged; only the citation was wrong.) |
| **CRIT-16** | P3 | S6 | **Accepted; option 3 chosen (restate honestly).** The "zero additional scans" claim is withdrawn. S6 now states the true cost — **up to 4 full-column scans per `materialize` on the `from_dataset` path, 2 when both selections are explicit** — with the reason: `materialize()` takes concrete sequences, so expansion happens in the S9 CLI verb while the check runs inside `flow/materialize.py` after `:837`, on opposite sides of an API boundary, and neither `workspace.py:302-316` nor `:318-338` memoizes `scan.distinct_values`. We deliberately did **not** memoize on `Workspace` or relocate the check into the CLI, because keeping it in the flow protects direct `public.py` callers who bypass the CLI — the safety property is worth two scans. Cross-referenced to R7 in both directions; R7's text now names the doubled scan cost, and P2 gains the timing task. |

**Re-derived counts and cross-references for this pass.** Step ids unchanged: S1–S15 + C1–C4 + P1–P5 = **24 steps** (15 + 4 + 5; the earlier “21” was an arithmetic error, corrected at landing per ARCH-19 — no step was added, removed, or renumbered) (no step added, removed, or renumbered this pass). Build Gate items remain **16**, enumerated in P5. Risks R1–R11 = 11, unchanged in count; only R7 and R11 changed text. Intent Reconciliation candidates remain **IR-1 … IR-5**, unchanged in wording. Every reference touched this pass was re-checked: S7 ↔ S14 ↔ R11 now state one protocol; S6 ↔ R7 ↔ P2 now state one cost story; S3 ↔ S4 ↔ the two registry test files now state one import direction; S8's `list runs` mechanism appears in exactly two places (S8 and the Integration test list) and agrees in both. No dangling reference remains.

---

# ADR — vqapr framework-agent bridge

## Decision

Build the framework-to-agent half of the vqapr agent layer in one cycle: six core CLI verbs
(`new`, `register`, `materialize`, `run`, `publish`, `list`) plus a `skill` verb group, four measured
friction fixes, a stage/family registry surfaced as `vqapr.descriptors`, and a single-source `SKILL.md`
installed by `vqapr skill install` with a thin adapter for the Claude target. Defer the agent-to-user
interview guide and the PRD §11.4 sample journey.

## Drivers

1. **The verification loop is already built and currently blocked at its first rung.** The external testbed
   at `kaist-thesis/vqapr-testbed/` records `F-001 — vqapr agent install is documented but does not exist`
   at severity `blocked`, and it is the only open item in that testbed's handoff. Nothing downstream can be
   measured until a skill can be installed.
2. **The one-shot measurement must not be spent on an unattributable bundle.** A fresh agent's naivete
   survives exactly one attempt, so the plan ships once and spawns twice: agent A stops after rung 1
   (registration), agent B runs rungs 2-3 after A's friction log is read.
3. **Drift must be structurally impossible where it is cheap, and honestly bounded where it is not.**
   `stage` and `family` are enumerable and become a registry; reason codes are composed at 37 callsites
   and are deliberately left free-form rather than pretending to a guarantee the code cannot keep.

## Alternatives considered

- **Verbs-first / friction-fixes-first sequencing.** Rejected: the registry changes the shape of the failure
  envelope that every other component documents, so doing it last forces the skill body and the descriptors
  render to be written twice.
- **Full reason-code enumeration with runtime enforcement (spec options R2/R3).** Rejected at interview
  Round 5: it requires touching all 37 `Failure.bounded()` callsites and risks the ~60 tests that assert
  exact code strings, for a guarantee the Build Gate does not need.
- **`vqapr describe` as a runtime introspection verb instead of a generated catalog.** Rejected at interview
  Round 4 in favour of `vqapr.descriptors` plus an install-time render, so the installed copy is always the
  installed package's truth without adding a verb whose output is a second authority.
- **Full `SimulationResult` serialization for resumable runs.** Rejected: three `object`-typed fields and
  hash-reproved opaque payloads make it a new format design. Only `final_state.recorder_rows` plus manifest
  and finalization provenance are persisted — exactly what `publish_run_record` consumes.
- **Copying the full skill body into both target directories.** Rejected on observed evidence: the two
  existing skills in the consuming repo already have divergent `.claude/` and `.agents/` copies.

## Why chosen

The chosen shape is the smallest one that makes the blocked loop run end to end while leaving no
copy that can silently go stale. Each rejected alternative either widens blast radius for a guarantee the
acceptance gates do not require, or introduces a second source of truth.

## Consequences

- `run` becomes a mutating command. `.vqapr/runs/<id>/` is a second on-disk mutable area and inherits the
  existing atomic temp → fsync → `os.replace` protocol; the workspace lock is deliberately not reused
  because the run directory path is unique per run and never read-modify-written.
- `run_id` is `FrozenRun.identity` and is path-dependent, so a run cannot be reproduced in a second project
  root. The rung-3 byte-identity check therefore persists once and copies the run directory.
- Reason-code drift remains undetectable by construction. This is recorded as a known limitation, not a gap.
- `constraint:no-import` becomes review-enforced rather than code-enforced for `agent/sample/`. See IR-4.
- Canon and code disagree until the four canon edits land; records 047-050 carry the reasoning.

## Follow-ups

- Agent-to-user interview guide (deferred component `skill-user-bridge`).
- PRD §11.4 sample journey (deferred component `sample-journey`).
- `MISSION-B.md`, written only after agent A's friction log is read.
- Reason-code registry (interview option R2), if a second real consumer appears.

---

# Intent Reconciliation

**Status: five open confirmations. The user deferred reconciliation mid-gate to continue on another
machine.** Per the workflow contract these are recorded here as open confirmations rather than resolved.
They are questions for the user, not for another planning pass — both review lanes reached consensus
(Critic `OKAY`, Architect `CLEAR`/`APPROVE`) with these outstanding.

Each item is a point where the consensus plan refines something the approved deep-interview spec asserted.
None of them reverses a spec decision; each changes a mechanism or a literal.

| id | What the spec said | What the plan does | Why it needs the user |
|---|---|---|---|
| **IR-1** | The stage registry is "enforced at `collector()` entry ONLY" (interview Round 11, option N1) | Placement is preserved exactly, but `collector(` is called at only 6 sites in 3 files and every stage the Build Gate exercises bypasses it. A **static exhaustiveness test** becomes the coverage mechanism; `collector()` stays as the runtime supplement and must raise `VqaprError` on a registered meta-stage, never a bare `ValueError` | The spec named `collector()` as the drift barrier. It is now the guard, not the barrier |
| **IR-2** | Build Gate item 4 is `vqapr new run-spec > spec.yaml` | `vqapr new run-spec --out spec.yaml`. Writing raw YAML to stdout breaks `envelope.py`'s one-JSON-line guarantee, which is the contract the whole agent-facing design rests on | It amends the literal text of an approved acceptance item |
| **IR-3** | `materialize` and `publish` both take a YAML spec "like `register`/`run`", while Build Gate 14 writes `vqapr publish <run_id>` | `run` writes `publish-spec.yaml` into the run directory at persist time, so the positional id resolves to a YAML spec and both statements hold | The spec asserted two different surfaces; this picks a reconciliation |
| **IR-4** | Locked intent `constraint:no-import`; Technical Context states `src/vqapr/agent/` holds only an empty `__init__.py` and two READMEs | The repo contradicts that: 7 tracked files including 4 modules importing `vqapr.public` and `vqapr.extension.fingerprint`, plus a live test. The constraint is scoped to new files and `agent/sample/` is recorded as an explicit pre-existing exemption | **Both reviewers flagged this as the IR deserving closest attention.** It converts a stated constraint into a review-enforced one. The alternative is a migration step that expands scope beyond the spec |
| **IR-5** | "canon 수정 4건과 각각의 구현 기록" | Four records, 047-050. Separately, edit (iv) widens beyond §10.4 to the architecture layout tree (`:2752-2757`), §13 step 2, and PRD §11.3, all of which place `descriptors.py` inside `agent/` or describe the old verb set | The widening is drift correction for the same decision, but it touches two sections the spec did not enumerate |

**Recommended answer to IR-4 when the interview resumes:** scope the constraint to new files *and* add a
boundary test that pins the exemption list, so the exemption cannot silently grow. That keeps the scope the
spec authorized while restoring code enforcement over the part that matters.

---

# Landing Punch List (applied to this final artifact)

| id | Fix | Applied |
|---|---|---|
| **ARCH-19** | Step count stated as 21 in three places; the breakdown enumerates 24 (S1-S15 = 15, C1-C4 = 4, P1-P5 = 5). Critic verified all 24 present and dependency-closed, so this is a documentation error, **not** uncounted steps | yes |
| **ARCH-20** | CRIT-15's rationale cited `materialize.py:838-846`, a guard inside `materialize()`; `publish_run_record` has no `dataset_exists` check across `:717-819`. Corrected to `:466-474` plus the already-correct `:532`. Requirement unchanged | yes |
| **CRIT-17** | `tests/agent/test_descriptors.py` named no mechanism for "without importing `vqapr.domain`". Now specifies a clean-subprocess `sys.modules` probe and cites the repo precedent at `tests/boundaries/test_capability_absence.py:86-103` | yes |
| **CRIT-18** | S4 cited `errors.py:179-180`; `def collector` is at `:178` with its return at `:179`, and the Test Plan had already been corrected to `:178-179`. S4 now agrees | yes |
| **counter-review** | The Architect's pass-3 line-drift advisory was judged **1 of 3 correct** by the Critic. Its proposed `flow/run.py:373-378` and `flow/materialize.py:794` "corrections" are **not** applied | not applied, deliberately |

---

# Consensus Record

| pass | Planner | Architect | Critic |
|---|---|---|---|
| 1 | `stage-01-planner.md` sha `203ba696` | `BLOCK` / `REQUEST CHANGES`, 15 findings (P1=5) sha `b620c8a2` | `ITERATE`, 14 findings (P1=4) sha `2ef65916` |
| 2 | `stage-02-revision.md` sha `92da98ff`, 29 findings accepted / 0 rejected | `WATCH` / `COMMENT`, 3 new (P1=0), 14 resolved + 1 partial sha `854e80b7` | `OKAY`, 2 new (P3), 14/14 resolved; counter-review found no Architect scope inflation sha `3599e143` |
| 3 | `stage-03-revision.md` sha `57e1a548`, 5 findings + 1 partial closed | **`CLEAR` / `APPROVE`**, 6/6 errata closed, 2 new P3 cosmetic sha `638f8847` | **`OKAY`**, 2/2 errata closed, 2 new P3; `CLEAR` judged justified sha `433e6601` |

Typed conflict gate: no conflicts at any pass — no `add` vs `remove` or `remove` vs `change` pair against
the same target id. Consensus openers used: 3 of a maximum 5. Total findings raised across the run: 36,
all dispositioned, 0 rejected.

**Status: pending approval.** No product source has been modified. Execution requires separate approval.
