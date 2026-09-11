# `skill install` writes into the enclosing repository's git root, not the project that installed vqapr, and `--project-root` cannot steer it

**Status: RECEIVED 2026-09-11 (접수) — confirmed against `develop` `b8b47e6c`; being fixed on `develop` on the owner's instruction.** All three findings reproduce from `src/vqapr/cli/skill.py`: the root is the nearest `.git` ancestor (1); `Path(".")` has no parents, so the walk from an unresolved `--project-root .` sees nothing (2); the refusal carries no `retry`, so `fix` falls back to the generic sentence (3). A fourth, not in the report: the stale-skill note every other command prints (`upgrade_note`) reads the *workspace* root, so skills written to an enclosing `.git` root are never checked.

| | |
|---|---|
| vqapr version | `0.14.4` (`vqapr skill list` → `package_version`; `uv pip show vqapr` → `Version: 0.14.4`) |
| installed from | `git+https://github.com/jaepil-choi/vqapr@b8b47e6c181e65d76e8a2589fd012002dff7c8d2` |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-demo-testbed`, Claude Code session (Opus 5) |
| python / OS | 3.12.13 / Windows 11 Enterprise 10.0.26200 |

## What I was doing

Setting up a new testbed that records the install-and-first-run demo. The testbed is its own uv
project (`vqapr-demo-testbed/pyproject.toml`, its own `.venv`) living one directory inside another
git repository (`kwam-enhanced-index/`, which is not a vqapr project and has its own agent skills).
I ran the two install lines the demo shows — `uv add vqapr`, then `uv run vqapr skill install` —
from inside the testbed directory.

## What I expected

That the skills land in the project that ran `uv add vqapr`, i.e. the directory the same envelope
reports as `workspace_root`. Two things on the public surface set that expectation:

- `vqapr --help`, on `--project-root`: *"workspace root: where `.vqapr/` is or will be (default: the
  current directory; refused when an ancestor directory already holds a workspace and this one does
  not, so a command run from a subdirectory cannot start a second workspace by accident -- pass the
  ancestor, or this directory, explicitly)"*. Every other command refuses to write into a directory
  the caller did not name.
- Given that, I expected `--project-root .` to be the explicit way to say "this directory".

`vqapr skill install --help` does say `--into INTO  install into this directory instead of the
auto-detected .git root`, so the default is documented. What surprised me is how far outside the
project that default reaches, that it does so with `ok: true` and no note, and the three findings
below.

## What happened

**1. The default target is the enclosing repository, above the workspace, and nothing flags it.**
From the testbed directory the real install wrote 10 skill directories and a `.vqapr-skill.json`
manifest into *each* of `kwam-enhanced-index/.claude/skills/` and `kwam-enhanced-index/.agents/skills/`.
The envelope reports `root` (the enclosing git root) and `workspace_root` (the testbed) as two
different directories and still returns `ok: true` with no note. Dry run, same directory:

    $ uv run vqapr skill install --target claude --dry-run
    {"ok": true, "root": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index", "skills": {"claude": {"analyze-result": {"absent": ["SKILL.md", "references/panels-from-tables.md", "references/paper-figures.md", "references/plotting-environment.md", "references/reading-a-record.md", "references/report-sections.md", "references/result-tables.md", "scripts/check_plotting_env.py"], "state": "absent"}, "inspect-workspace": {"absent": ["SKILL.md", "references/deleting.md", "references/reuse-judgement.md"], "state": "absent"}, "introduce-vqapr": {"absent": ["SKILL.md", "references/install-and-environment.md", "references/mental-model.md", "references/reading-the-envelope.md", "references/sample-journey.md"], "state": "absent"}, "make-compliance": {"absent": ["SKILL.md", "references/declaring-data.md", "references/observe.md", "references/the-box.md", "references/tolerance.md"], "state": "absent"}, "make-datamodel": {"absent": ["SKILL.md", "references/datamodel-or-strategy.md", "references/output-schema.md", "references/reading-inputs.md", "references/running-a-datamodel.md"], "state": "absent"}, "make-exchange": {"absent": ["SKILL.md", "references/access-and-account.md", "references/cost-model.md", "references/execution-profiles.md", "references/fill-timing.md"], "state": "absent"}, "make-strategy": {"absent": ["SKILL.md", "references/composition-and-budget.md", "references/factor-portfolios.md", "references/memory-and-payload.md", "references/public-helpers.md", "references/reading-inputs.md", "references/rebalance.md"], "state": "absent"}, "register-dataset": {"absent": ["SKILL.md", "references/correcting-a-registration.md", "references/discouraged-preparation.md", "references/grain-and-cost.md", "references/point-in-time.md", "references/price-axis.md", "references/timezone-proof.md", "references/universe-and-tradability.md", "scripts/profile_source.py"], "state": "absent"}, "report-issue-dev": {"absent": ["SKILL.md", "references/report-template.md", "references/what-counts-as-a-defect.md"], "state": "absent"}, "run-backtest": {"absent": ["SKILL.md", "references/check-before-run.md", "references/feeding-the-next-run.md", "references/records-and-tweaks.md", "references/run-declaration.md", "references/watching-and-failures.md"], "state": "absent"}}}, "stage": "skill.install.dry_run", "targets": ["claude"], "workspace_root": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-demo-testbed", "written": ["D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-analyze-result\\SKILL.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-analyze-result\\references\\panels-from-tables.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-analyze-result\\references\\paper-figures.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-analyze-result\\references\\plotting-environment.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-analyze-result\\references\\reading-a-record.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-analyze-result\\references\\report-sections.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-analyze-result\\references\\result-tables.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-analyze-result\\scripts\\check_plotting_env.py", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-inspect-workspace\\SKILL.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-inspect-workspace\\references\\deleting.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-inspect-workspace\\references\\reuse-judgement.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-introduce-vqapr\\SKILL.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-introduce-vqapr\\references\\install-and-environment.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-introduce-vqapr\\references\\mental-model.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-introduce-vqapr\\references\\reading-the-envelope.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-introduce-vqapr\\references\\sample-journey.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-compliance\\SKILL.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-compliance\\references\\declaring-data.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-compliance\\references\\observe.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-compliance\\references\\the-box.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-compliance\\references\\tolerance.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-datamodel\\SKILL.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-datamodel\\references\\datamodel-or-strategy.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-datamodel\\references\\output-schema.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-datamodel\\references\\reading-inputs.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-datamodel\\references\\running-a-datamodel.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-exchange\\SKILL.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-exchange\\references\\access-and-account.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-exchange\\references\\cost-model.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-exchange\\references\\execution-profiles.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-exchange\\references\\fill-timing.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-strategy\\SKILL.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-strategy\\references\\composition-and-budget.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-strategy\\references\\factor-portfolios.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-strategy\\references\\memory-and-payload.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-strategy\\references\\public-helpers.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-strategy\\references\\reading-inputs.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-make-strategy\\references\\rebalance.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-register-dataset\\SKILL.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-register-dataset\\references\\correcting-a-registration.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-register-dataset\\references\\discouraged-preparation.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-register-dataset\\references\\grain-and-cost.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-register-dataset\\references\\point-in-time.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-register-dataset\\references\\price-axis.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-register-dataset\\references\\timezone-proof.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-register-dataset\\references\\universe-and-tradability.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-register-dataset\\scripts\\profile_source.py", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-report-issue-dev\\SKILL.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-report-issue-dev\\references\\report-template.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-report-issue-dev\\references\\what-counts-as-a-defect.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-run-backtest\\SKILL.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-run-backtest\\references\\check-before-run.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-run-backtest\\references\\feeding-the-next-run.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-run-backtest\\references\\records-and-tweaks.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-run-backtest\\references\\run-declaration.md", "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\.claude\\skills\\vqapr-run-backtest\\references\\watching-and-failures.md"]}

**2. `--project-root .` from the same directory flips it into a refusal.** Same cwd as above, where
the command without the flag found a `.git` one level up:

    $ uv run vqapr --project-root . skill install --target claude --dry-run
    {"correlation_id": null, "error": "InputError: skill install needs a .git root (or pass --into)", "failures": [{"cause": {"message": null, "origin": null, "traceback": null, "type": null, "where": null}, "code": "argument.no_git_root", "example_total": 0, "examples": [], "fix": "correct the input named above, then retry", "observed": "no .git found above .", "requirement": "skill install needs a .git root (or pass --into)", "source": {"file": null, "key_path": null, "line": null}, "status": 404}], "mutation": false, "ok": false, "retry_precondition": null, "stage": "usage", "workspace_root": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-demo-testbed"}

`observed` says `no .git found above .` although there is one directly above that directory, and
the command without the flag found it.

**3. In a fresh folder with no git above it, the documented install refuses, and the `fix` names no
input.** This is the path a first-time user takes (empty folder → `uv add vqapr` → `skill install`):

    $ vqapr skill install --target claude --dry-run      # cwd: C:\tmp\vqapr-nogit, no .git above
    {"correlation_id": null, "error": "InputError: skill install needs a .git root (or pass --into)", "failures": [{"cause": {"message": null, "origin": null, "traceback": null, "type": null, "where": null}, "code": "argument.no_git_root", "example_total": 0, "examples": [], "fix": "correct the input named above, then retry", "observed": "no .git found above C:\\tmp\\vqapr-nogit", "requirement": "skill install needs a .git root (or pass --into)", "source": {"file": null, "key_path": null, "line": null}, "status": 404}], "mutation": false, "ok": false, "retry_precondition": null, "stage": "usage", "workspace_root": "C:\\tmp\\vqapr-nogit"}

`fix` says *"correct the input named above, then retry"*, but the user passed no input. The way
out (`--into .` or `git init`) appears only in the `requirement` text.

## Reproduction

1. Inside any git repository `R`, create a subdirectory `P` with its own `pyproject.toml`, and run
   `uv add vqapr` in `P`.
2. From `P`: `uv run vqapr skill install --target claude --dry-run` → `root` is `R`, `workspace_root`
   is `P`, `ok: true`. **Finding 1.**
3. From `P`: `uv run vqapr --project-root . skill install --target claude --dry-run` → 404
   `argument.no_git_root`, `no .git found above .`. **Finding 2.**
4. From an empty directory with no `.git` above it: `vqapr skill install --dry-run` → 404
   `argument.no_git_root`, generic `fix`. **Finding 3.**

Finding 1 happened 3 of 3 times: the real install, a dry run from the testbed path, and a dry run
from a Windows junction pointing at the testbed. Findings 2 and 3 happened once each; they are
dry runs and write nothing.

## Impact

Worked around. The cost was not time but a side effect on another project:

- The real install wrote 22 untracked paths into a repository that is not a vqapr project.
- A Claude Code session already open at that repository's root **immediately listed the ten
  `vqapr-*` skills as its own available skills**. That is an agent in an unrelated project picking
  up instructions it never asked for.
- I removed the 22 paths by hand. The repository's pre-existing, tracked skill directories
  (`.claude/skills/vqapr-skill/`, `.agents/skills/vqapr/`) were not touched by the install, because
  the names differ.

For the demo it means the slide's "two lines" do not hold. In a fresh folder you need `git init`
first or `--into .`. In a nested project you need `--into .`, or the skills go somewhere else.

## What would have prevented it

- Default to the directory the command runs in (the `workspace_root` the envelope already reports),
  or refuse when the git root differs from it and name both. That is the rule `--project-root`
  already applies to the workspace.
- Make the `no_git_root` refusal's `fix` name the commands that resolve it: `--into .` or `git init`.
- Make `--project-root .` resolve the same way the implicit current directory does.
