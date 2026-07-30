# The skill owns the repair, so it has to offer more than one

Status: complete

## Purpose

PRD 5.6 made the core report a journey stage and refuse to prescribe a repair. PRD 5.3 is the
other half of that decision: the *skill* owns the repair, and for each stage it must give the
agent the stage contract, the failures that actually occur there, **a list of repair paths per
failure rather than one**, the criterion for choosing between them, which choice needs the user's
confirmation, and the public command to rerun afterwards.

Today the generated skill states the principle and one worked example (a string in a numeric
column at `STRATEGY_RUN`). PRD 5.3 says in as many words that a skill offering a single path
fails the requirement — the principle paragraph is not the deliverable, the per-stage paths are.
Without them the agent that receives `STRATEGY_CONTRACT: Strategy must declare at least one
Strategy-specific pandas input` has a stage name and nothing to do with it, which is the exact
position the stage model was supposed to end.

## Scope and non-goals

In scope: a stage-recovery table owned by the skill layer, rendered into the generated skill
package, covering all eleven stages in `errors.STAGES`, plus tests that keep it honest.

Non-goals:

- No change to `errors.py`, to any `QlibxError`, or to what `qlibx errors <stage>` answers. The
  core keeps reporting and keeps not prescribing.
- No promotion of `portfolio.py` / `reporting.py` bare `ValueError`s. See Discoveries: those two
  stages have no failures in the agent vocabulary at all, and this task documents that state
  rather than changing it.
- No new CLI command. The content ships inside the generated skill package.

## Acceptance criteria

- Every stage in `errors.STAGES` has at least one documented failure; every failure has **two or
  more** repair paths, a selection criterion per path, an explicit confirmation flag, and a rerun
  command that is a public `qlibx` command or a documented public Python entry point.
- The failures are grounded in raises that exist in the package, not invented.
- `documentation` does not import the recovery content: the repair paths must be structurally
  unreachable from the core's `qlibx errors <stage>` surface, which PRD 5.6 forbids from
  prescribing.
- `uv run pytest` stays green in both shells (`145 passed` at `0e0bb41`); `ruff check` clean.
- The new module is placed in `tests/test_architecture.py::LAYERS` deliberately.

## Repository context

- `src/qlibx/errors.py` — `STAGES`, eleven entries, each a one-line responsibility. The stage
  summary in the skill must be generated from this, not retyped.
- `src/qlibx/skill.py` (460 lines) — `_skill_files()` maps relative path to content;
  `_alpha_operations_markdown()` is the precedent for a reference file generated from installed
  data rather than hand-copied. `_skill_markdown()` holds the SKILL.md body, whose `## Error
  recovery` section (line ~213) is where the principle currently lives.
- `tests/test_architecture.py::LAYERS` — layer 0 is the dependency-free kernel; `documentation`
  sits in layer 1; `skill` in layer 5. A module importing only `errors` belongs in layer 1.
- Real raises per stage, counted from the source: `STRATEGY_RUN` 36, `DATA_REGISTRATION` 35,
  `RESEARCH_RECORD` 21, `EXECUTION` 13, `STRATEGY_CONTRACT` 13, `PROJECT` 3, `ONBOARDING` 6,
  `ALPHA` 6, `UNIVERSE` 2, `PORTFOLIO` 0, `REPORTING` 0.

## Milestones

- [x] M1: `stage_recovery.py` with `RepairPath`/`StageFailure`/`STAGE_RECOVERY`, the renderer, and
      content for the first six stages. Wired into `_skill_files` as
      `references/stage-recovery.md`; SKILL.md's error section points to it.
- [x] M2: Content for the remaining five stages, including the honest treatment of `PORTFOLIO`
      and `REPORTING`.
- [x] M3: Invariants in `tests/test_stage_recovery.py` and the layering entry.
- [x] M4: Full validation, implementation record.

## Progress

Complete. Eleven stages, 24 failures, 61 repair paths, rendered into
`references/stage-recovery.md` in the generated skill package.

M1 and M2 were written as one pass. Splitting the table by stage would have meant deciding the
rendering twice; the milestone boundary was a scheduling guess, not a real seam.

Tests went into a new `tests/test_stage_recovery.py` rather than `test_agent_onboarding.py` as
planned — onboarding tests are about planning and applying files, and these are about the content
being plural. The ownership test lives in `test_architecture.py`, where the import graph already is.

## Discoveries

- **`PORTFOLIO` and `REPORTING` raise nothing.** Both are declared in `errors.STAGES` and neither
  appears in a single `QlibxError`; `portfolio.py` has 13 bare `ValueError`s and `reporting.py`
  6. A skill section for those stages therefore cannot say "you will receive stage `PORTFOLIO`" —
  the agent receives an unclassified `ValueError`. Writing paths for the two stages as if they
  were in the vocabulary would document a product that does not exist. They get their contract
  summary, the failures that actually occur, and a statement of how those failures arrive today.
- `tests/test_architecture.py::test_importing_the_facade_does_not_load_the_execution_runtime`
  still uses `subprocess.run(text=True)`, the pattern that `0e0bb41` removed from the acceptance
  helper. It passes because its child prints nothing, so the locale decode never sees non-ASCII.
  Latent, not a defect today; out of scope here.

## Decision log

- **The recovery content lives in its own module, not in `skill.py` and not in
  `documentation.py`.** Not in `documentation.py` because that module backs `qlibx docs` and
  `qlibx errors`, the core surfaces PRD 5.6 forbids from prescribing a repair; a test asserting
  `documentation` never imports the recovery module turns that ownership rule into something
  executable rather than a comment. Not in `skill.py` because eleven stages of prose would double
  that file.
- **Structured data, not markdown prose.** A `StageFailure` carrying a tuple of `RepairPath` lets
  a test assert "two or more paths, each with a criterion" — a prose blob can only be grepped for
  keywords, which is how a requirement like this rots.

## Validation

Baseline `0e0bb41`: `145 passed` under both PowerShell and bash, `ruff check` clean.

After: `161 passed` under both, `ruff check` clean. Mutation checks and their results are
recorded in `docs/implementations/017-stage-recovery-in-the-skill.md`.

One finding came out of writing rather than testing: the first draft used em-dashes, which cannot
be encoded on this machine's cp949 console. The generated file is written as UTF-8 so it was
never at risk on disk, but any agent piping the reference through a legacy console would have hit
it. The content is ASCII now and a test asserts it.

## Risks and recovery

- **Inventing failures.** Every documented failure must trace to a raise in the package. Risk is
  a plausible-sounding recovery guide for errors that never occur, which is worse than no guide.
  Mitigation: each failure names the message it comes from.
- **Restating the core's `expected` as a repair.** The two must stay distinguishable: `expected`
  says what the contract required, a path says what the agent may do about it.
- Recovery: one commit per milestone group on `exp/one-shot` after `0e0bb41`.

## Next action

None. The follow-up this task exposed and deliberately did not take: promote the bare
`ValueError`s in `portfolio.py` (13), `reporting.py` (6) and `optimization.py` (22). That is what
would let `PORTFOLIO` and `REPORTING` drop the "these arrive unclassified" note the reference
currently carries.
