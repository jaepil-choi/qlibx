# 030 — The skill's Rung 1 stop condition is a command shape the CLI refuses

**Status:** **half closed 2026-08-31** by
`docs/implementations/101-both-members-of-the-lookback-pair-are-reachable.md` (branch
`fix/033-the-lookback-pair-is-reachable`). Item 1 is done: the Rung 1 stop condition now names one
`vqapr list <kind>` call per kind, names the remaining three, and says there is no all-kinds form so
the `cli.usage.rejected` refusal is predicted rather than discovered.
`tests/cli/test_the_stop_condition_is_runnable.py` keeps the sentence and `list_.KINDS` in step, and
fails if `list` ever grows the all-kinds form this file argues is the better shape.

**Item 2 is still open and is a decision, not an omission.** Whether `cli.usage` sits inside the
six-field envelope guarantee has to be settled before either side is edited, and nothing here
forecloses it.

**Status when filed:** open. Found 2026-08-30 by the first-time-user journey in
`kaist-thesis/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-001**,
`papercut` / `docs`. It was the very first command of the run.
**Touches:** `src/vqapr/agent/skill/SKILL.md:179`; `src/vqapr/cli/list_.py:87`;
the `cli.usage` envelope.

## The stop condition names a command that does not exist

`SKILL.md:179` reads, verbatim:

> **Stop condition:** `vqapr list` shows all required elements and `register` accepted every
> declaration without failures.

`list_.py:87` makes `kind` a mandatory positional. So the reporter ran the sentence and got:

```json
{"ok": false, "stage": "cli.usage",
 "error": "UsageError: the following arguments are required: kind",
 "failures": [{"code": "cli.usage.rejected", "observed": "vqapr list",
               "requirement": "the following arguments are required: kind"}]}
```

There is no `all` kind and no default. Checking the stop condition means ten calls, and knowing to
make ten calls means reading `vqapr list --help` — not the skill. The sentence is the first
instruction a new reader acts on and it is not runnable.

Either the sentence names the kinds, or `list` grows an all-kinds form. The second is the better
shape for what the sentence is actually asking — *what does this workspace already hold?* is one
question, not ten — but the first closes the defect.

## The second half: `cli.usage` refusals carry three of the six guaranteed fields

`SKILL.md`'s "Reading vqapr's output" section says *"Every entry carries `code`, `source`,
`requirement`, `observed`, `fix` and `explain`"*, and tells the reader to read `fix` first. The
refusal above carries `code`, `observed`, `requirement` and nothing else. There is no `fix` to
read, on the first refusal a new user will ever see.

**The reporter could not tell whether this is issue 016 and said so**, per the testbed's
instruction to write an unclear case as new. It is worth settling explicitly, because the two are
plausibly different: 016 is about failures raised *inside the simulation callback*; this is the
argument parser refusing before anything is loaded.

If the six-field guarantee is only meant to cover validation failures and not argument-parser
usage errors, **the guarantee needs the exception written into it** — as phrased it has none.

## What to settle

1. Make the Rung 1 stop condition runnable, or name the ten kinds in it.
2. Decide whether `cli.usage` is inside or outside the six-field envelope guarantee, and write the
   answer into whichever of the two is wrong.
