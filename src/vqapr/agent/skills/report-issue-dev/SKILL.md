---
name: report-issue-dev
description: Files a defect or friction report about vqapr itself into the upstream repository's issue directory, as a dated Markdown file naming the exact vqapr version, the scenario, the commands run, and the refusal envelope verbatim. Use when work on vqapr hits a package defect (status 500 or 502), a refusal whose `fix` does not resolve it, a documented command or option that does not exist or behaves differently than documented, a result that looks wrong, or friction that cost real time — and this project is a testbed or evaluation whose findings go back to the vqapr maintainers.
---

# Report a vqapr defect upstream

vqapr is under active development and this project is one of the places it gets exercised. A
defect you hit and work around is a defect the next person hits. **Write it down where the
maintainers read it, before you resolve it** — the workaround changes what you remember.

## Decide first: is this a vqapr defect?

The refusal envelope answers most of this itself. Every command returns one line of JSON, and a
failure carries `status`, `stage`, `cause`, `fix`, `requirement`, `observed` and `source`.

| what you saw | file a report? |
|---|---|
| `status` **500** or **502** | **Yes, always.** These mean a vqapr defect by definition. Do not work around it silently |
| `status` **423** or **503** | **No.** Retry the same command unchanged. Report only if it never clears |
| `status` **400/404/409/422** and `fix` resolved it | No. That is the envelope working |
| `status` **400/404/409/422** and `fix` did **not** resolve it, or named something that does not exist | **Yes.** A `fix` that does not fix is a defect in the message |
| A skill, docstring or `--help` describes a command, flag or behaviour that is absent or different | **Yes** |
| A run completed but a number is wrong, or two commands disagree about the same fact | **Yes.** This is the heaviest kind |
| Something took far longer than the shape of the work justifies | **Yes.** File it as friction |
| You misread the docs and the docs were right | No |

Reproduce it once before filing. A report you could not repeat is worth filing only if you say so
in it — see [references/what-counts-as-a-defect.md](references/what-counts-as-a-defect.md) for the
borderline cases and what the status codes mean.

## Where the file goes

The upstream checkout is a **sibling project on this machine**, not this project. The issue
directory is:

```text
DevProjects/vqapr/docs/issues/
```

Find it by walking up from this project's root until a parent directory contains
`vqapr/docs/issues/`. From a testbed one level inside its project — the usual layout — that is:

```bash
ls ../../vqapr/docs/issues/          # DevProjects/<project>/<testbed>/ -> DevProjects/vqapr/
```

Write your file there with a dated name and no number:

```text
../../vqapr/docs/issues/report-2026-09-09-check-refuses-a-dataset-run-accepts.md
```

- `report-` prefix, then `date +%Y-%m-%d`, then a kebab-case slug that **states the problem**, not
  the area. `report-2026-09-09-register-loses-the-timezone.md`, not `report-2026-09-09-register.md`.
- **Never take a number.** `NNN-` names belong to issues the owner has triaged, `src/` cites them
  as decision authority, and two testbeds picking a number at the same time collide.
- **Create nothing but your own file.** Do not edit, renumber, move or delete anything already in
  that directory, and do not touch `README.md` or `archive/`.

**If that directory does not exist**, the upstream checkout is not on this machine. Write the same
file into `vqapr-reports/` at this project's root instead, and say so in your message to the user
so they can carry it over. Do not go looking for another place to put it.

## Read nothing else upstream

Filing is a **write**. Reaching into the upstream repository to diagnose is not, and it destroys
what this project is for: the whole value of a testbed finding is that it came from someone who
only had the public surface. Do not open `src/`, `tests/`, `docs/`, or the existing issue files to
work out why something failed, and do not let what you find there change what you report.

Report what the public surface did: the command, the envelope, the documented promise it broke.
Naming a cause you did not verify is the exact defect issue `077` was filed about.

## What every report carries

Two things are not optional, because without them a report cannot be acted on.

**The version.** Take it from the package, not from memory:

```bash
uv run vqapr skill list          # "package_version" in the JSON
uv pip show vqapr                # Version, and Location if installed from a wheel
```

**The envelope, verbatim.** Paste the failing command's entire JSON line, unedited and unsummarized.
Do not paraphrase it into prose, do not drop fields you think are empty, and do not pretty-print it
into something you retyped by hand. The maintainers grep those fields.

Everything else — scenario, expectation, what happened, reproduction, impact, workaround —
[references/report-template.md](references/report-template.md) has as a skeleton with a filled
example. Copy it; do not invent a shape.

## After you file it

1. Tell the user, in one line: what you filed, and the path you wrote it to.
2. Say what you did next — the workaround, or that you are blocked. Record the workaround **in the
   report** as well, under Impact; a defect someone is already routing around is more urgent, not
   less.
3. Keep working. Filing is not a stop condition unless the defect actually blocks the scenario.

## What this skill will not do

- File a report for a mistake of your own that the message correctly diagnosed.
- Guess a cause, a subsystem, or a fix. `observed` and `expected` are yours; the diagnosis is not.
- Edit anything in the upstream repository other than the one file it creates.
- Read upstream source or documentation to write the report.
