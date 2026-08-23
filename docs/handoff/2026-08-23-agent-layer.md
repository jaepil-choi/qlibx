# Handoff — the agent layer has a plan, and the plan is not approved yet

Status: **pending approval**, five open confirmations
Branch: `jaepil-develop` · head `2918fb9` at planning time · **no production source was touched**
Written because the work continues on a different machine and `.gjc/` does not travel.

---

## Read this first: what is in this directory and why

Three files carry everything. They sit in `docs/handoff/` rather than `.gjc/` on purpose —
`.gitignore:41` ignores `/.gjc/` with the comment *"GJC workflow state is per-session local scratch,
never shared"*, so the entire interview and consensus run would otherwise have been lost at the
machine boundary.

| file | what it is |
|---|---|
| `2026-08-23-agent-layer-spec.md` | the approved requirements spec. 18 interview rounds, final ambiguity 4.4% against a 5% threshold, status PASSED |
| `2026-08-23-agent-layer-plan.md` | the final consensus plan, its ADR, the intent-reconciliation items, and the landing punch list. This is the `pending approval` artifact |
| `2026-08-23-agent-layer-reviews.md` | the six Architect/Critic review bodies, concatenated. Evidence behind all 36 findings |

**Start with the plan, not the spec.** The plan supersedes the spec wherever they differ, and it
records every divergence explicitly rather than silently.

---

## Where the work stands

Nothing has been implemented. The tree was clean before this handoff and the only new files are the
four in this directory. What exists is a settled description of what to build and why, produced by
two gated workflows:

```
deep-interview   18 rounds, ambiguity 100% -> 4.4%    -> spec, PASSED
ralplan          3 openers of a maximum 5             -> plan, CLEAR + OKAY consensus
                 36 findings raised, 0 rejected
approval         NOT GIVEN                            -> pending
```

The consensus loop converged rather than timing out. Pass 3 closed with Architect **`CLEAR` /
`APPROVE`** and Critic **`OKAY`** on the same artifact. The typed conflict gate found no conflicts at
any pass. The last four findings were cosmetic P3 errata and were applied to the final artifact
before it was frozen.

Ambiguity did not fall monotonically, and that is deliberate. It rose twice: at Round 4 when
choosing the registry refactor expanded scope, and at Round 16 when a scoring omission was caught
and corrected. Both rises are recorded in the spec's Trigger Metadata.

---

## What must happen before anything is built

**Five intent-reconciliation items are open.** The planner surfaced them, both review lanes
confirmed them, and they were about to be put to the user one at a time when the session moved
machines. None was answered, and none was answered on the user's behalf. Full text is in the plan
under `# Intent Reconciliation`.

| id | the short version | why it needs a human |
|---|---|---|
| **IR-4** | `constraint:no-import` becomes review-enforced rather than code-enforced for `agent/sample/` | **Both reviewers flagged this as the one deserving closest attention.** The spec's own Technical Context is factually wrong: it says `src/vqapr/agent/` holds "an empty `__init__.py` plus two READMEs", but `git ls-files src/vqapr/agent/` returns 7 tracked files including 4 modules that import `vqapr.public` and `vqapr.extension.fingerprint`, and `tests/agent/test_sample_panel.py:16-23` imports them. A locked Round 0 intent was written against an inventory that does not exist |
| **IR-1** | `collector()` entry enforcement is the runtime guard, not the coverage mechanism | The spec named `collector()` as the drift barrier. It is called at only 6 sites in 3 files, and every stage the Build Gate exercises bypasses it. A static exhaustiveness test becomes the real coverage mechanism |
| **IR-3** | `publish` takes a positional `<run_id>` that resolves to a `publish-spec.yaml` written by `run` | The spec asserted a YAML-spec surface and Build Gate item 14 asserted a positional id. Two surfaces, one reconciliation |
| **IR-2** | Build Gate item 4 becomes `vqapr new run-spec --out spec.yaml` | Writing raw YAML to stdout breaks `envelope.py`'s one-JSON-line guarantee, which is the contract the whole agent-facing design rests on. It amends the literal text of an approved acceptance item |
| **IR-5** | Four canon records 047-050, and canon edit (iv) widens beyond §10.4 | The widening is drift correction for the same decision, but it touches two sections the spec did not enumerate |

Ask them in that order, highest impact first. If any answer reveals divergence from intent, the
correction routes back through a Planner revision and both review lanes before finalizing. Three
consensus openers of five were used, so two remain.

**A recommendation for IR-4, since it is the sharp one:** scope the constraint to new files *and*
add a boundary test that pins the exemption list, so the exemption cannot silently grow. That keeps
the scope the spec authorized while restoring code enforcement over the part that still matters.

---

## What the plan decides

Four components in scope, two deferred. Framework-to-agent comes first; the agent-to-user interview
guide and the PRD §11.4 sample journey are explicitly out of this cycle — the latter because
`kaist-thesis/vqapr-testbed/` already plays that role with 4,962 names of real data, and building a
sample would give the work two verification stages.

- **cli-surface** — final verb set `new register materialize run publish list skill`. `materialize`
  and `publish` are new. `run` gains narrow persistence to `.vqapr/runs/<id>/`: only
  `final_state.recorder_rows` plus manifest and finalization provenance, never the full
  `SimulationResult`. Four measured friction fixes: empty-workspace `list` must succeed, a missing
  input file must not become `stage:"unhandled"`, every subcommand gets help text, and a template
  emitter produces declaration and run-spec YAML.
- **skill-cli** — `vqapr skill install|remove|list` with `--target codex|claude|both`. Full text
  lives only at `.agents/skills/vqapr/`; `.claude/skills/vqapr-skill/SKILL.md` is a thin adapter
  pointing at it. Install root is the `.git` root, `--into` overrides, dry-run prints the resolved
  path first. A manifest records package version, per-file sha256, and the sha of each *source*
  skill file, so an editable install detects content drift without a version bump. `AGENTS.md` and
  `CLAUDE.md` are never touched.
- **skill-framework-bridge** — the `SKILL.md` body carries only when-to-use plus the three-rung
  mission path, 80-124 lines with frontmatter. Verb detail is duplicated nowhere; `--help`, the
  template emitter and the rendered catalog answer detail on demand. This requires the authority
  split **CLI owns usage, skill owns remedy**, which is why the `cli/main.py` docstring and PRD §2.6
  are edited.
- **descriptors** — `vqapr.descriptors` exposes `STAGES`, `FAMILIES`, `VERBS`, imports nothing from
  `vqapr.domain`, and is rendered into `references/stages.md` at install time. Reason codes stay
  free-form on purpose; the existing code strings are preserved so the ~60 tests asserting them keep
  passing.

### Five facts the consensus loop established that overturned earlier assumptions

1. **`run_id` must not be minted.** `FrozenRun.identity` is already a sha256 over every frozen
   declaration and is already stamped on every recorder row. A second id would give one run two
   identities and break `publish_run_record`'s provenance.
2. **`run_id` is path-dependent**, so a run cannot be reproduced in a second project root. The
   rung-3 byte-identity check therefore persists once in root A and copies the run directory to
   root B rather than re-running.
3. **`publish` cannot be standalone today.** `publish_run_record` takes an in-memory result and `run`
   writes nothing. That is exactly what forces the narrow persistence.
4. **`materialize` never checks instrument membership.** A partial ticker mismatch yields zero rows
   for that name, publishes, and exits 0. The testbed's friction log has no severity that can record
   a confidently wrong answer, so a `wrong` severity is being added to it.
5. **`descriptors` cannot generate a full error-code catalog.** Codes are f-string-composed at 37
   callsites and some are passed in by the caller; only `stage` and `family` are statically
   enumerable. The architecture's §10.4 claim is narrowed to match, which is canon edit (iv).

---

## Acceptance, in two gates

**Build Gate** — 16 command-to-observable items, verified by us in an empty directory in under 30
minutes with no source reading. The dominating item is number 14: in a *new shell*,
`vqapr publish <run_id>` returns `ok:true`. Its precondition chain transitively asserts the template
emitter, the registry, all three mission rungs, and the cold-process boundary that motivated the
persistence work in the first place.

**Spawn Gate** — measured by a fresh agent in `kaist-thesis/vqapr-testbed/`, not by us: zero
vqapr-attributable `blocked` friction entries, at most two `slowed`, zero reads of `qlibx/src/`
self-logged so the count is auditable, each rung's first invocation succeeding within three tries,
rungs 1-2 matching numbers frozen before the spawn, and rung 3 producing byte-identical in-process
versus cold-process publish output.

The two gates answer different questions. The Build Gate asks whether we built it. The Spawn Gate
asks whether it is usable by someone who has never seen it — and only the second one is the point.

**Pre-spawn tasks**, all in the plan's work breakdown: measure and freeze the source parquet's row,
date and instrument counts; freeze the rung-2 coverage target; lift the 10 inline stage literals in
`data/scan.py` and `flow/preflight.py`; write `MISSION-A.md`; land the four canon edits with records
047-050. `MISSION-B.md` is deliberately *not* written yet — it is written after agent A's friction
log is read, so it cannot prejudge what A discovers.

---

## The verification loop this feeds

```
edit qlibx  ->  bump version  ->  vqapr skill install into the testbed
            ->  spawn agent A (rung 1: registration, then stop)
            ->  read FRICTION.md
            ->  write MISSION-B.md  ->  spawn agent B (rungs 2-3)
```

`kaist-thesis/pyproject.toml` consumes vqapr as `{ path = "../qlibx", editable = true }`, so code
changes appear with no publish step. Skill resources do not — they are copied, which is why the
manifest tracks source shas.

The loop is currently blocked at its first step. `vqapr-testbed/FRICTION.md` records **F-001,
severity `blocked`**: *"`vqapr agent install` is documented but does not exist"*. Note the root
cause the plan preserves — F-001 is not caused by the missing command but by
`src/vqapr/agent/skill/README.md` describing an unbuilt command in the present tense. Renaming the
verb to `skill install` without fixing that README re-files F-001 verbatim. That is canon edit (iii).

---

## Two things to be careful about

**The step count in the plan said 21 and the breakdown enumerates 24.** This was caught as ARCH-19
and corrected in the final artifact. The Critic verified all 24 steps are present and
dependency-closed, so it was a documentation error, not uncounted work. Mentioned here because a
reader who saw an earlier draft may remember 21.

**The Architect's pass-3 line-drift advisory is only one third correct.** The Critic counter-reviewed
it and found its proposed `flow/run.py:373-378` and `flow/materialize.py:794` corrections wrong. They
are deliberately **not** applied. The plan's Landing Punch List records this so nobody helpfully
"fixes" them later.

---

## How to verify any of this

```
uv run pytest -q                      # 609 passing at head 2918fb9
uv run ruff check src/ tests/         # clean
```

Neither was run during planning and neither needed to be — nothing was implemented. Both are the
declared gates for the implementation work when it starts.

---

## Resuming

1. Read `2026-08-23-agent-layer-plan.md`.
2. Answer IR-4, IR-1, IR-3, IR-2, IR-5 with the user, in that order, one at a time.
3. If nothing diverges, take the plan to approval and hand it to execution. If something diverges,
   route the correction back through a Planner revision and both review lanes first.
4. Do not start implementing before step 2 finishes. IR-4 in particular changes what a boundary test
   must enforce, and IR-3 changes the shape of a CLI verb.
