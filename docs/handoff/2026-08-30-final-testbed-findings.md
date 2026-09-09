# Handoff — 2026-08-30: the final testbed's findings, filed as 015-027

Thirteen issues filed from one journey. This file is the index and the proposed order; every claim
below is stated in full in the issue it names.

## The source

`kwam-enhanced-index/vqapr-final-testbed/` — a Fama-French 3-factor replication over 2,251 KRX
instruments, 2019-07 to 2026-07, run against the built wheel `vqapr-0.2.0a1` by an agent with no
access to this repository's source, tests, docs or history. Its deliverables:

```
FINDINGS.md   the friction log, fifteen entries, written during the run
REPORT.md     the strategy result, its conventions, and the biases it carries
```

Read `FINDINGS.md` before working any of these — the issues carry the evidence, but the log carries
the sequence, which is what shows how each gap was actually reached.

**The journey completed.** Six declarations registered on the first attempt, three runs finished in
under 30 seconds each over 2,251 instruments, and `check` produced what the reporter calls the
single best-formed diagnostic they have seen from any tool. Twelve of the thirteen issues below are
about the distance between what the package does and what it says it does.

## The map

| issue | log entry | severity | kind |
|---|---|---|---|
| **015** — `run` does not make the judgments `check` makes | F-010 | `blocked` | code |
| 016 — a callback failure drops half the envelope | F-005/6/7 | `slowed` | message |
| 017 — the template offers an account mode that does not exist | F-005 | `slowed` | code + message |
| 018 — `invested` is gross with an undocumented ceiling of 1 | F-006, U-001 | `slowed` | docs + code? |
| 019 — a diagnostic table must be declared, and only the refusal says so | F-007 | `slowed` | message |
| 020 — the costed venue cannot hold a short | F-003 | `slowed` | docs |
| 021 — a validated Fama-French sort ships unadvertised | F-002 | `slowed` | docs |
| 022 — `vqapr.fill` has no clock | F-011 | `slowed` | code |
| 023 — a digest describes a file that can change under it | F-009 | `slowed` | docs + code? |
| 024 — a run that declared a table reports none | F-008 | `papercut` | code + docs |
| 025 — the stale-skill message names a flag that does not exist | S-001 | `papercut` | message |
| 026 — four of nine kinds do not emit the key the help promises | F-001 | `papercut` | message |
| 027 — nothing makes a convention be spoken aloud | P-001 | proposal | docs |

Not filed, because they are the reporter's costs and not the package's, and neither has an upward
part: **F-004** (the vendor share-count extract is missing 2016-2017, which moved the deliverable's
start date three years) and **N-001** (Windows console encoding, duckdb reserved words, a deprecated
duckdb API, and two colliding account-code mappings — the last being the single largest time cost of
the run, ~20 minutes, and entirely the data's). **B-001** is the testbed boundary working as
designed: the agent asked for a benchmark outside its directory instead of reading it.

## Proposed order — a proposal, not a decision

**First, alone: 015.** It is the only one that costs a user a wrong answer they cannot see. It is
also the only one whose fix is a product decision rather than an edit — three options are laid out
in the file and option 2 is argued for. Nothing else should ride along with it.

**Then the callback-boundary group: 016, 019, 018, 017.** 016 is the shared defect and the other
three are what a reader hits because of it. Doing 016 first makes 019 nearly free (its remedy is one
`fix` sentence) and makes 018's open question — is the cap an invariant or a leftover — the only
thing left in that file. 017 belongs here because its message half is the same class, though its
template half is independent and could go at any time.

**Then the record group: 022, then 024.** In that order, because `022` fixing `event_time` on
`vqapr.fill` is what makes 024's unexplained `formations: 1` explicable; doing 024 first means
writing a note about a number that is about to change.

**Then the docs group: 021, 020, 025, 026.** All four are sentences. 021 is one line in the skill
and has the largest payoff of anything in this list relative to its cost — four of this journey's
findings were resolved by `dir(vqapr.public)`, which the skill never mentions.

**Held for a decision, not scheduled: 023 and 027.** 023 must be read against `docs/issues/archive/009`
first — the behaviour it reports is the behaviour 009 deliberately created, and only its docs half
is unambiguous. 027 is a proposal about `register`'s envelope that the reporter themselves marked
not-attributable.

## Two cross-references worth not rediscovering

**015 is not 012.** `docs/issues/archive/012` was `check` refusing a spec `run` completes, and the answer
was that the judgment was wrong. Here the judgment is right and `run` never asks it. Same observable
shape, opposite cause.

**023 is not 009 reopening.** 009 removed the fingerprint gates on purpose and its "What not to do"
forbids putting one back. 023 asks for a *statement* in `show run`, and for the skill to stop
promising the gate that 009 removed.
