# Re-scope — the agent layer becomes three tiers, and only Tier 1 is built now

Supersedes the scope of `2026-08-23-agent-layer-plan.md`. **Does not supersede its findings.**
The 36 findings, the ADR, and the five established facts all still hold; what changes is how much
of it is built before the first measurement.

---

## Why this exists

The plan was reviewed against the stated purpose:

> agent가 vqapr을 설치한 뒤 막힘없이 필요한 기능들을 쓸 수 있고, 각 CLI command가 무엇을
> 의미하는지 추측하지 않고 이해할 수 있으면 된다.

Two properties: **installable-and-unblocked**, and **self-explanatory**. Measured against them,
24 steps was roughly three times the necessary size.

The decisive evidence is `kaist-thesis/vqapr-testbed/FRICTION.md`. It records exactly two entries,
and only one is vqapr-attributable:

| id | severity | attributable | cause |
|---|---|---|---|
| F-001 | `blocked` | yes | `agent/skill/README.md` describes `vqapr agent install` in the present tense; no such command exists |
| F-002 | `slowed` | **no** — the log says so itself | `uv sync` replaced a ROCm torch build |

Its `## Registration`, `## Derivation`, `## Strategy and run`, and `## Measurement` sections are
all still `_(first entries go here)_`. The testbed never reached the CLI. A 24-step plan was
resting on one measured blocker.

## The loop this serves

```
build a tier  ->  spawn an agent into the testbed  ->  read FRICTION.md
              ->  fix what it actually hit         ->  build the next tier
```

The spawn is the measuring instrument and the friction log is the deliverable. This inverts the
sizing rule: a tier is not "everything that would be good", it is **the smallest thing that makes
the next spawn worth its cost.** Anything a spawn has not yet justified is deferred *by design*,
not by budget.

## The three tiers

### Tier 1 — installable and self-explanatory *(built now)*

| step | from plan | what |
|---|---|---|
| T1-1 | S5(c) | Every verb and every argument carries `help=`/`description=` |
| T1-2 | S5(a) | `list` on a workspace-less directory returns `ok:true, count:0` |
| T1-3 | S10(b) | Missing file / re-run / malformed spec become typed stages, not `unhandled` |
| T1-4 | S10(d) | `vqapr new run-spec --out` emits a complete run spec |
| T1-5 | S11 | `SKILL.md` — when-to-use plus the mission path, no verb detail |
| T1-6 | S12 | `vqapr skill install\|remove\|list` |
| T1-7 | C3 | Both agent READMEs stop describing unbuilt commands |
| T1-8 | S15 | `src/vqapr/__main__.py` |

### Tier 2 — deferred until a spawn asks for it

`run` currently discards its result (`cli/run.py:176-181` keeps only `occurrences` and
`account_version`). That is a real gap. It is **not** in Tier 1, reversing an earlier
recommendation, because the friction log shows the testbed has not reached Registration — let
alone a run — so nothing has yet measured *what shape* the result must take. Building it now
would repeat the mistake this re-scope corrects.

### Tier 3 — separate tracks, not this plan

- **`vqapr.descriptors` registry** (S1-S4, C4). Legitimate drift-prevention work, but whether
  `stage` strings are literals or constants does not change what `--help` prints. Own track.
- **`materialize` membership check** (S6). A partial ticker mismatch yields zero rows, publishes,
  and exits 0 — a **silently wrong answer**. This is a correctness bug and belongs in
  `docs/issues/`, not bundled with a CLI-comprehensibility plan.
- **Persistence + `publish`** (S7-S9, S14) — Tier 2's full form, if measurement justifies it.
- **Spawn apparatus** (P1-P5) — judged after Tier 1 lands.

## What this does to the five open IRs

| id | status under Tier 1 |
|---|---|
| IR-1 | **moot** — belongs to the descriptors track |
| IR-2 | **live, and resolved by construction.** `new run-spec --out PATH`, never stdout redirection: `envelope.py:131-132` writes exactly one JSON line to stdout, so YAML on stdout would break the one contract the agent-facing design rests on |
| IR-3 | **moot** — `publish` is not in Tier 1 |
| IR-4 | **moot** — no new module under `agent/` imports anything from `vqapr.*` except through the CLI, so the constraint holds for new files without needing an exemption for `agent/sample/` |
| IR-5 | **reduced to one edit**, C3, which is drift correction with no widening |

Four of five open confirmations dissolve because they were attached to Tier 2/3 concerns.

## Acceptance for Tier 1

Verified in an empty directory, in a fresh shell, reading no source:

1. `vqapr --help` names all verbs, each with a one-line description
2. Every verb's `--help` is non-empty and every argument has help text
3. `mkdir t && cd t && vqapr list datasets` → `ok:true, count:0`, exit 0
4. `vqapr new run-spec --out spec.yaml` writes a spec whose every required key is present
5. `vqapr register missing.yaml` → typed stage, not `stage:"unhandled"`
6. `vqapr new datamodel x --dataset d` twice → typed refusal on the second
7. `vqapr skill install --dry-run` prints the resolved path and writes nothing
8. `vqapr skill install` places `SKILL.md`, then `vqapr skill list` reports it
9. `python -m vqapr --help` behaves as `vqapr --help`
10. Neither agent README mentions `vqapr agent install`

Then spawn Agent A, let it run until it blocks, and read the friction log.

## Spawn A's cap

The 2026-08-23 plan stopped Agent A after rung 1 to protect a fresh agent's naivete. That
reasoning is kept but re-cut: **cap by blocker, not by rung.** Agent A proceeds until it logs its
second `blocked` entry or completes, then stops. One root cause cascading into five entries makes
attribution worthless, which is what the rung cap was really protecting against; naivete itself is
renewable, since the next spawn is a new agent.

Status: Tier 1 authorized and in progress. Tiers 2 and 3 unauthorized pending measurement.
