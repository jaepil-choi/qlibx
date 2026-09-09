# 199 — A tenth skill, whose subject is vqapr being wrong rather than vqapr being used

**Date:** 2026-09-09. **Branch:** `develop`. **Reported by:** the owner, for the testbed campaign —
`kwam-enhanced-index/` and `kaist-thesis/` each run agent sessions against a shipped wheel, and
what those sessions find has been arriving by hand.

## Why

The findings from testbed sessions are the most valuable defect reports this project gets, and
they are the ones most likely to be lost.

They are valuable because of what the reporter does **not** know. A testbed agent has the installed
public surface and nothing else — no `src/`, no design documents, no memory of why a refusal is
worded the way it is. Every issue in `docs/issues/archive/` numbered `055` and up came from that
position, and the heaviest ones (`071`, `075`, `078`, `087`) are heavy precisely because someone
without the implementation could not get past them.

They are lost because filing them had no mechanism. The instruction that existed was a paragraph
in `introduce-vqapr/SKILL.md` headed *"Friction logging"* which said to write friction down and
called the log a deliverable — without saying where the log goes, what it must carry, or who reads
it. In practice the reports landed in whatever file the testbed happened to have: `FINDINGS.md`,
`VQAPR-ISSUES.md`, `KNOWN-ISSUES.md`, a handoff document in a third repository. Two of those were
reset between runs; the run-3 findings survive only because a copy was made into
`kaist-thesis/docs/handoff/`, and `docs/issues/README.md` says so.

The gap the reports had in common was **the version**. A finding without one cannot be placed:
`0.4.1` and `0.6.0` disagree about most of the surface, and triage on nine of the run-4 reports
went to re-confirming which build had been observed rather than to the defects.

**Why a tenth skill and not a section in an existing one.** Discovery. Only `name` and
`description` are preloaded (§11.2), and the nine descriptions are all shaped around what the user
is trying to *do with* vqapr — register data, write a strategy, read a result. "This is broken and
I want the maintainers to know" matches none of them, so the instruction sitting inside
`introduce-vqapr` was reachable only by an agent that had already decided to re-read an orientation
document. That is the same defect the nine-way split was made to fix.

## What

`src/vqapr/agent/skills/report-issue-dev/` — `SKILL.md` and two references.

**Where it writes.** `DevProjects/vqapr/docs/issues/`, found by walking up from the project root
until a parent holds `vqapr/docs/issues/` — from a testbed one level inside its project, that is
`../../vqapr/docs/issues/`. When no such checkout exists (any real user), it writes to
`vqapr-reports/` in the project instead and says so. The skill creates its own file and nothing
else: no edits to `README.md`, `archive/`, or anyone else's report.

**No number.** `report-YYYY-MM-DD-<slug>.md`. `NNN-` names belong to issues the owner has triaged
and `src/` cites them as decision authority; an untriaged report holding one makes the citation
unreadable, and two testbeds filing at once would collide on the same next integer. Triage assigns
the number.

**Write-only upstream.** The skill forbids opening upstream `src/`, `tests/`, `docs/` or existing
issues to diagnose. This is the load-bearing rule: the finding's whole value is that it came from
someone who only had the public surface, and reading the implementation destroys that in a way
nothing downstream can detect. `AGENTS.md`'s testbed isolation says the same for every other
purpose; this skill is the one authorized crossing, and it crosses in one direction.

**The version is mandatory and read, not recalled** — `vqapr skill list` reports
`package_version`, `uv pip show vqapr` reports the wheel it came from. Both are in the template's
header table.

**The envelope goes in whole.** Pasted unedited, not paraphrased. This follows the rule the skills
already hold to (§11.2, record `171`): a refusal carries `status`, `stage`, `cause`, `fix`,
`requirement`, `observed` and `source`, and prose restating those loses the fields triage greps.

**`references/what-counts-as-a-defect.md`** turns `status` into the triage decision, which it
already is: 500 and 502 are always reported, 423 and 503 never are, the 4xx family only when `fix`
did not fix. It also names the four kinds worth filing — a wrong envelope, two parts of the package
disagreeing, a wrong number, and friction — and forbids the two things a testbed agent cannot
honestly supply: a cause it did not verify, and a patch.

**`references/report-template.md`** is the skeleton plus one filled example. Every heading is
required; a section with nothing in it says why. "Could not reproduce" is an answer, a missing
section is not.

## Trade-offs

**Ten skills, not nine.** §11.2 called the set nine and the axis was "what the user came to do".
The tenth has a different axis and the PRD now says so rather than pretending it fits.
`tests/agent/test_every_shipped_skill_obeys_the_contract.py` discovers the set from the directory,
so nothing enumerated nine and nothing had to change to admit a tenth.

**Reports land unnumbered in a numbered directory.** They sort apart by prefix and
`docs/issues/README.md` states the rule, but the directory now holds two kinds of file. The
alternative — a separate inbox directory — was not taken because the owner asked for
`docs/issues/`, and because a report nobody sees while reading the ledger is a report that does not
get triaged.

**The skill ships to every user, and most have no upstream checkout.** The fallback keeps it from
failing confusingly, but a PyPI user who reaches for it will write a file into their own project
and have to send it on themselves. The alternative — filing over the network — is a network call
this package does not otherwise make and credentials it has no way to hold.

## Validation

- `uv run python -m pytest tests/agent -q` — the ten-skill contract set: name matches directory,
  description says what and when and is third-person, body under 500 lines (SKILL.md is 107),
  every bundled file linked from `SKILL.md`, no second-hop references, forward slashes, no CR
  bytes.
- `uv run python -m pytest tests/ -q -m ""` before the release.
- `uv run python scripts/record_shipped_skills.py` then `--check` — the three new files enter
  `_shipped.json` at `0.9.0.dev1`.
- `uv run vqapr skill list` reports ten `available`.
