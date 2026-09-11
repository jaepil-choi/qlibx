# Installing the skills, and what the verdicts mean

## The commands

```bash
vqapr skill install                 # both targets
vqapr skill install --target agents # or claude
vqapr skill install --dry-run       # every file's state and what would be written
vqapr skill install --force         # overwrite files that hold edits
vqapr skill list                    # what is installed, per skill and per file
vqapr skill remove [--force]
```

The root is the workspace root, the directory every other command works in (the current directory,
or `vqapr --project-root <dir>`), or `--into <dir>`. In a fresh folder that is where `uv add vqapr`
ran; no `git init` is needed. `AGENTS.md` and `CLAUDE.md` are never touched.

## Where they land

```
.agents/skills/vqapr-<skill-name>/
.claude/skills/vqapr-<skill-name>/
```

**Both targets get identical bytes.** Neither is a pointer to the other — a pointer would cost the
reader an extra hop, and a copy that drifts is now detectable instead of merely feared.

## The three verdicts

`skill list` judges each installed file against **every release vqapr has ever shipped**, by
content:

| verdict | means | what install does |
|---|---|---|
| `current` | the same as this package ships | nothing |
| `outdated` | an earlier release's copy, untouched | **updates it silently** |
| `modified` | matches no release vqapr has shipped | **refuses**, and names the file |

`--force` overwrites the refused set and nothing else.

The point of the split: an outdated file has nothing to lose, and a modified one holds someone's
edit. Telling both to "just reinstall" is how an edit gets destroyed.

A file at a path vqapr **never shipped** — a note the user added under `references/` — is reported
as preserved and is not touched, by `install` or by `remove`.

## Why a copy might read as `modified` when it is not

The judgment is content-only, so a truncated download and a hand edit look the same. Both need
`--force` and a human glance, and the sentence we can honestly write — *this differs from every
release vqapr has shipped* — is true of both.

One case where this is a false alarm: a developer running an unreleased build. Their previous copy
came from a build that was never released, so it is in no release history.

## The upgrade note

After a package upgrade, every command except `skill` itself prints one line to **stderr**:

```
vqapr: the agent skills in ... were installed from vqapr 0.6.0; this is 0.7.0.
Run `vqapr skill install` to update them.
```

stdout still carries exactly one JSON document. The note is on every command rather than on
`skill list` alone, because a stale skill does its damage while an agent reads it and runs
something else.

## The environment

vqapr's console script lives in the virtual environment. A project managed by uv reaches it as
`uv run vqapr`; an activated environment as `vqapr`. **Use one form consistently** — mixing them is
how a command "works sometimes".

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed and the environment
is simply not activated. That is not a broken install and does not need reinstalling.
