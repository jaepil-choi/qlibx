# 177 — Running and reading become two skills, and the skill contract becomes a test

**Closes:** PRD §11.2 (three more of the nine), §9.4 (`UC-REPORT-001` — the renderer is the
project's). **Branch:** `develop`, on top of record `176`.

## Why

`run-backtest` and `analyze-result` are the two halves the old body mixed most. Its "Rung 2"
explained executing a run and then, without a break, how to register a run's output table as a
dataset; its "Rung 3" explained reading a record and then how to draw a figure for a journal. Both
are real subjects and neither is the other.

`analyze-result` is also the one skill that has to touch the user's environment. PRD §9.4 keeps
plotting out of the package on purpose — the values must render through any renderer — so on a
fresh project the libraries a figure needs are simply absent, and that is a conversation rather
than a step.

## What was built

**`run-backtest/`** — SKILL.md and five references: `run-declaration.md`, `check-before-run.md`,
`watching-and-failures.md`, `records-and-tweaks.md`, `feeding-the-next-run.md`.

`check-before-run.md` carries the counting trap in full: the envelope's `checked` list has four
entries and the eight judgments all happen inside one of them, so counting the list and expecting
eight is the mistake to warn about rather than a shortfall to report. It also takes D-5's fourth
fragment — **423 and 503 mean retry the same command unchanged** — which the refusal envelope
cannot say for itself.

`records-and-tweaks.md` states the counting rule the other way round: *count records, not
directories*, because a killed run leaves a directory with rows and no record, and it says plainly
that `rm run --cascade` crosses several kinds and should be shown to the user before it runs.

**`analyze-result/`** — SKILL.md, five references, and `scripts/check_plotting_env.py`.

The script reports which of pandas / matplotlib / numpy are present, which dependency manager the
project actually uses — read from `uv.lock`, `poetry.lock`, `Pipfile.lock`, `environment.yml`,
`pyproject.toml` — and the command that would add **exactly what is missing**. It installs nothing.

Reading the manager rather than assuming `pip` is the point: `pip install` into a uv-managed
project writes into an environment the lockfile does not describe, the next `uv sync` removes it,
and from the outside that looks like the install never happened.

The skill's own instruction is the same three steps every time: use what the project already
renders with; otherwise say what is missing and why, show the command, and ask; install only after
the user agrees. Never add anything to vqapr itself.

**`tests/agent/test_every_shipped_skill_obeys_the_contract.py`** — PRD §11.2's rules, enforced
mechanically on every skill as it lands. The name matches the directory; the description says both
what and when, in third person, within 1,024 characters; the body is under 500 lines; every
bundled reference is pointed at from SKILL.md and every script is named by filename; nothing is
reachable only on a second hop; paths use forward slashes.

A rule kept by hand across nine directories is a rule that holds for the first three.

**`introduce-vqapr`'s frontmatter was fixed now rather than at the end.** It still holds the
pre-split body, but it ships today, and `name: vqapr` with the abstract one-line description was
the defect this whole campaign started from. Its body length is `xfail(strict=True)` until the
other eight are cut — so the day it is finally cut, the test fails for *passing* and the marker
has to be removed deliberately.

## What the tests found

**A cross-platform hash defect, and the fix is `.gitattributes`.**

The frontmatter regex would not match `introduce-vqapr/SKILL.md`. The cause was not the regex: the
file held CRLF. This repository is developed with `core.autocrlf=true`, which stores LF in the
object database and checks out CRLF on Windows — so **a wheel built on Windows and a wheel built
on Linux ship different bytes for the same commit.**

Record `175` made those bytes the identity of an installed file. Every hash in `_shipped.json`
would have been true on the platform that generated it and wrong on the other, and a user who had
touched nothing would have been told their skills were edited — which is exactly the accusation
that whole mechanism exists to avoid making.

`.gitattributes` now forces `text eol=lf` on `src/vqapr/agent/skills/**`, the tracked files were
renormalized, and a test asserts no shipped skill file carries a CR byte. Caught before the first
release wrote a table, so no recorded hash is wrong.

**Two of my own rules, held to.** The reference-depth test first forbade sibling links outright and
flagged `discouraged-preparation.md` pointing at `point-in-time.md`. That is stricter than the
rule, which protects against a file reachable *only* on a second hop — `point-in-time.md` is
offered by SKILL.md directly. The test was rewritten to the precise condition rather than the
prose to the stricter test.

**The line count in records 175 and 176 was wrong.** They said 1,011 lines; the committed file is
1,019. The 1,011 was measured while a parallel session was mid-edit on record 173. Both records
were corrected — a number presented as a measurement has to be one.

## Trade-offs

**`analyze-result` ships one script and prose recipes, not a plot library.** Figures vary per
paper, so rendering is a high-freedom task where instructions beat a fixed script; the environment
check is deterministic, so it is a script. The split follows the fragility of the task rather than
a preference for one form.

**`introduce-vqapr` now duplicates all three of the cut skills' subjects.** Deliberate until every
skill is cut: deleting first would leave a window where content lives in neither place.

## Validation

- `uv run pytest tests/ -q` — 1,527 passed, 25 deselected, 1 xfailed. The two `tests/extension/`
  failures are a parallel session's `43f59eb0` and predate this work.
- `uv run ruff check src/ tests/agent` — clean.
- `tests/agent/` — 59 passed, 1 xfailed.
- `check_plotting_env.py` run against this repository reports `uv` and
  `uv add --group dev matplotlib`, naming only what is missing; run against a directory with no
  lockfile it says so and marks the command a guess.
- `vqapr skill install` into a scratch project writes all four skills' files, subdirectories
  included.
