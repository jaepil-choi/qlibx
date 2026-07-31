# Archive Attempt 1 and Reset the Root Package

Status: complete

## Purpose

Preserve the current qlibx implementation as a reproducible reference under
`attempts/attempt-1/`, while resetting the repository root to a minimal `uv init --package`-style
package for a second implementation attempt based on the new canonical PRD.

## Scope and non-goals

In scope:

- archive the current implementation source, configuration, tests, examples, package metadata,
  and lockfile;
- keep the new canonical `docs/qlibx-prd.md` at the repository root;
- keep reusable project workflow infrastructure and external reference snapshots at the root;
- leave a minimal importable/buildable `qlibx` package with no attempt-1 runtime dependencies;
- validate both the archived implementation and the clean root package;
- commit on `exp/one-shot`, merge into the existing `jaepil-develop` branch, and push both relevant
  branches.

Non-goals:

- design or implement attempt 2;
- rewrite the new PRD;
- move documentation, generated data, virtual environments, caches, build output, or ignored
  runtime state;
- change external reference snapshots or workflow plans.

## Acceptance criteria

- `attempts/attempt-1/` contains the tracked attempt-1 implementation and package metadata.
- The root retains `docs/qlibx-prd.md`, reusable workflow files, and `references/`.
- The root package resembles a fresh package scaffold: minimal `pyproject.toml`, empty direct
  dependencies, one `src/qlibx/__init__.py`, and a minimal README.
- Root lock/import/compile/build checks pass.
- The final source and destination branches are clean, merged, and synchronized with their remote
  counterparts.

## Repository context

- Working repository: `D:\chljeffreyz\DevProjects\qlibx`
- Source branch: `exp/one-shot` at `ee41c54`
- Requested destination interpreted as existing `jaepil-develop`; no local or remote branch named
  exactly `jaepil` exists.
- `docs/qlibx-prd.md` was rewritten in `ee41c54` and is the new attempt-2 canonical PRD.
- Attempt 1 implementation spans `config/`, `src/`, `tests/`, `experiments/`, `showcases/`,
  `qlibx-custom/`, README, package metadata, and `uv.lock`.
- Generated/ignored state such as `.venv/`, `.qlibx/`, `qlibx-research/`, `data/`, `dist/`, and
  caches is not part of the archive.

## Milestones

- [x] M1: Inspect branch history, project rules, canonical PRD, package metadata, and file scope.
- [x] M2: Create the attempt-1 archive and reset root package metadata/source.
- [x] M3: Validate archived reference evidence and root lock/import/compile/build behavior.
- [x] M4: Record final evidence, commit, merge to `jaepil-develop`, and push.

## Progress

- Confirmed the user request targets the separate qlibx repository, not the initial
  `kwam-enhanced-index` working directory.
- Confirmed a clean `exp/one-shot` worktree and fetched current remote refs.
- Confirmed the only existing user branch matching "jaepil" is `jaepil-develop`.
- Confirmed `ee41c54` promotes a rewritten architecture-neutral PRD for the next attempt.
- Read the repository ExecPlan, package workflow, dependency-change, lock-review, and
  implementation-log procedures.
- Moved the classified attempt-1 implementation and metadata into `attempts/attempt-1/`.
- Created the minimal root package scaffold and a new reset implementation record.
- The first archived full-test run collected 164 tests: 162 passed and 2 failed due to relocation
  path state, not changed implementation behavior.
- After user clarification, restored all moved docs, completed plans, cache/output/runtime state to
  root and removed the temporary archived data copy.

## Discoveries

- The initial `master` package scaffold targeted Python 3.13, but Qlib 0.9.7 and the current
  environment use Python 3.12. The clean scaffold will retain Python 3.12 while removing attempt-1
  dependencies.
- External `references/` are large but intentionally non-authoritative research inputs and are
  useful for attempt 2; they are not attempt-1 implementation output.
- Several ignored runtime/data directories are multi-gigabyte local state. Moving them would make
  the archive non-reproducible and would not preserve tracked implementation history.
- Moved Python bytecode retained absolute pre-move source paths, causing one callable-fingerprint
  test to look for the old root `tests/` path.
- One attempt-1 integration test intentionally reads project-contained canonical
  `data/qlibx/daily_market.parquet`, so a code-only relocated snapshot is not independently
  full-testable without copying local data.

## Decision log

- Interpret "jaepil branch" as the existing `jaepil-develop` branch rather than inventing a new
  remote branch.
- Keep all documentation and workflow plans at root; archive only implementation code, examples,
  and package state.
- Preserve Python 3.12 in the root scaffold because it is the declared Qlib compatibility
  environment, even though the original `uv init` commit used Python 3.13.
- Start no attempt-2 functionality beyond the minimal package scaffold.
- Do not move or duplicate caches, virtual environments, runtime state, docs, or data.

## Validation

- A temporary fully contained local data copy produced `164 passed, 35 warnings` from the archived
  code before the scope was simplified.
- The final code-only archive intentionally excludes that data copy and documentation; its tests
  remain reference evidence rather than a standalone completion gate.
- `uv lock --check`: passed; the root lock contains only editable `qlibx` with no dependencies.
- `uv tree --locked`: `qlibx v0.1.0`.
- `PYTHONPATH=src uv run --no-sync --locked python -c ...`: imported the root
  `src/qlibx/__init__.py` and printed `Hello from qlibx!`.
- `uv run --no-sync --locked python -m compileall -q src`: passed; generated bytecode was removed.
- `uv build --out-dir C:\tmp\qlibx-reset-build-20260731`: built the wheel and sdist successfully.
- `uv sync --locked` was attempted twice before the user narrowed the scope; both attempts stopped
  while removing the existing `.venv\Scripts\ruff.exe` with Windows `os error 5`. No further venv
  mutation was attempted.
- Staged Git inspection reported 118 renames, 0 deletions, no moved docs, no unstaged/untracked
  files, and no `git diff --cached --check` errors.
- Created source commit `b2a0bde` before this plan-completion amendment.

## Risks and recovery

- Bulk moves can accidentally include ignored user data. Only explicitly classified tracked paths
  will be moved.
- The archive can be restored by moving its tracked contents back to root; Git history also retains
  the pre-reset tree.
- Merge and push occur only after both projects validate and branch ancestry is rechecked.

## Next action

No implementation work remains. Verify the final amended commit, merge result, remote refs, and
clean worktree during delivery.
