# 025 — The stale-skill message names a flag that does not exist

**Status:** **closed** by
`docs/implementations/095-the-stale-skill-message-names-a-real-command.md` (branch
`fix/025-stale-skill-message`). The message now names `vqapr skill install`, which already
overwrites a stale copy. No `--force` was added to `install`: it would have been a no-op existing
only to make an incorrect sentence correct, and a test now keeps it rejected.

**Status when filed:** open. Found 2026-08-30 while installing the package and the skill for the
final first-time-user journey in `kwam-enhanced-index/vqapr-final-testbed/`, before the run started.
Recorded there as **S-001**, `papercut`, ~1 minute. The evaluator's, not the agent's.
**Touches:** `src/vqapr/cli/skill.py:208-211`.

## What happens

```
$ vqapr skill list
{"current": false, "installed": true, "ok": true, "package_version": "0.1.0a11",
 "stage": "skill.list",
 "stale": "the installed skill differs from the one this package ships; run
           `vqapr skill install --force` to update it"}

$ vqapr skill install --force
{"error": "UsageError: unrecognized arguments: --force",
 "failures": [{"code": "cli.usage.rejected", "observed": "vqapr",
               "requirement": "unrecognized arguments: --force"}],
 "ok": false, "stage": "cli.usage"}
```

`vqapr skill install --help` accepts only `--target`, `--into` and `--dry-run`.

## Confirmed in this repository

`skill.py:208-211` emits the sentence. The `install` subparser (`skill.py:222-236`) takes
`--target`, `--into`, `--dry-run`. `--force` is added to the **`remove`** subparser
(`skill.py:238-243`), where it means *"remove even if files have been modified since install"*. So
the flag exists, on a sibling verb, with a different meaning.

## What resolved it

`vqapr skill install` with no flags. It overwrote the stale files, and `skill list` then reported
`current: true`, `package_version: 0.2.0a1`. **The remedy exists; only the sentence pointing at it is
wrong** — and the plain command was the obvious next thing to try, which is why this is a papercut
and not worse.

## What closes it

Either drop `--force` from the message, or accept it on `install` as a no-op alias.

Prefer dropping it. `--force` on `remove` guards a real condition (files modified since install);
adding a no-op `--force` to `install` makes one flag mean "override a safety check" on one verb and
nothing at all on its neighbour.

## Worth noting for the next stale-skill fix

An installed skill silently going stale has cost this project a measurement before — `docs/issues/archive/009`
records that the skill fingerprint (case E in its audit) was added *"after a stale installed skill
silently invalidated an agent-journey measurement"*. The detection works. This is only the sentence
it prints.
