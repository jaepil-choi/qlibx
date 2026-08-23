# 047 — A verb that says what it is, and a refusal that does not look like a crash

The first user of this CLI is an agent that has just run `uv add vqapr` and knows nothing else. Two
properties decide whether it can proceed: it must be able to learn what a verb does without reading
source, and a mistake in its own input must not look like the framework breaking.

Neither held.

## 1. The verb list explained nothing

```text
usage: vqapr [-h] [--project-root PROJECT_ROOT] {new,register,run,list} ...

positional arguments:
  {new,register,run,list}
```

That is the whole answer to "what can this do". `new`, `register`, `run` and `list` are generic
English, and an agent trying to find which one materializes data has to guess or read `src/`.
Across the entire CLI there were **three** `help=` strings; `register.py` and `run.py` had none, so
`vqapr register --help` did not even say what the positional argument was.

Every verb now carries a one-line summary in the verb list and a description of its contract in its
own `--help`, and every argument has help text.

The descriptions are **written for the CLI, not taken from the module docstrings.** Routing
`module.__doc__` into `description=` was tried first and is wrong on its own terms: those docstrings
argue about mechanism and history for whoever maintains the file, while an agent asking "what is
this verb" needs the contract and the next command. `register.py`'s docstring opens on dependency
ordering of declaration sections — true, and not an answer to the question being asked.

This required amending the `cli/main.py` docstring, which forbade what this change does. It said the
CLI "does not explain failures or offer remedies" as a single rule. The rule is now split along the
line that actually matters: **the CLI owns usage, the skill owns remedy.** Stating what a verb *is*
cannot be a second authority — there is no other source for it. Stating how to *recover* would be,
because the package's typed refusal already carries that judgement (PRD §2.6).

## 2. `--help` died on a legacy console

Fixing (1) broke `--help` completely, on the machine it was written on:

```text
$ vqapr skill --help
UnicodeEncodeError: 'cp949' codec can't encode character '\u2014'
exit 1, stdout empty
```

`argparse._print_message` ends at `file.write(message)`, so help text goes out through the console's
inherited code page. cp949 — the default on a Korean Windows console — cannot encode an em dash. The
first command an agent runs against an unfamiliar verb returned exit 1 and an empty stdout.

`envelope.emit()` already solved this for the envelope, and its docstring states the reason: *"A
legacy code page cannot encode characters that appear in ordinary failure text, and losing the
report to the reporting step is not acceptable."* Help was outside that discipline because it never
goes through `emit()`. `_Parser._print_message` now writes UTF-8 bytes to `stdout.buffer`, the same
way.

**Both fixes are kept although either alone hides the symptom today.** ASCII-only descriptions make
the text safe now; the byte-level write makes it safe after the next person edits that prose and
types an em dash. The first is the current text, the second is the guarantee.

## 3. Four refusals arrived as `stage:"unhandled"`

A missing file, a re-run of `new`, a malformed spec and an incomplete spec all left as bare
`FileNotFoundError` / `FileExistsError` / `TypeError` / `ValueError`. `envelope.failure()` cannot
name a stage for those, so all four were reported as `unhandled` — which tells an agent *the
framework broke*, sending it to read source instead of fixing its own input. Retrying is the most
common thing an agent does, so the `new` case is hit constantly.

`cli/inputs.py` adds one typed refusal covering user-supplied input, at stage `cli.input`:

| code | when |
|---|---|
| `cli.input.file_missing` | the named path does not exist |
| `cli.input.file_unreadable` | it exists and cannot be read |
| `cli.input.not_a_mapping` | it is not valid YAML, or parsed to something other than a mapping |
| `cli.input.file_exists` | writing would overwrite |
| `cli.input.keys_missing` | required keys are absent |

`family` is `None`, for the reason `UsageError` already uses it: `FailureFamily` is the closed set
of *package* stages (architecture §8.3) and an unread file never entered one. Picking a plausible
family would make an agent classify it wrongly.

### The side effect this exposed

The first version of (3) still wrote a diagnostics dump:

```json
{"stage":"cli.input","detail":"\\tmp\\t1\\.vqapr\\diagnostics\\unhandled.txt", ...}
```

`raise ... from error` chains the original exception, so the formatted traceback carries both frames
and crosses `MAX_INLINE_TRACEBACK_LINES`. `failure()` computed that dump **before** checking whether
the error had a bounded body — so a read-only refusal created `.vqapr/` in the user's project as a
side effect. A refusal that leaves a side effect is not a refusal.

`UsageError`'s existing carve-out was already the right shape, so it became a base class,
`BoundedRefusal`, with `InputError` alongside it. Both are refusals that never reached a package
stage and whose body is already complete evidence; for both, the traceback is noise. `VqaprError` is
deliberately untouched — its dump behaviour is about package-stage failures and is a separate
question.

## Validation

`tests/cli/test_agent_surface.py`, 21 tests.

The encoding test is the one worth naming. It must run **as a subprocess**: `capsys` replaces stdout
with a UTF-8 capture, so every in-process test stayed green while `--help` was completely broken on
a real console. It also injects non-ASCII into the parser rather than asserting against the shipped
descriptions, so it pins the *mechanism* and not today's text — verified by disabling
`_print_message` and confirming the test fails, then restoring it and confirming it passes.

```
uv run pytest -q            676 passed   (655 before, +21)
uv run ruff check src/ tests/   clean
```

Manually, in an empty directory with a fresh shell and no source reading: all five verbs print a
description; `list` succeeds on an uninitialised directory; the four refusals arrive typed with no
`detail`, no `traceback`, and no `.vqapr/` created; `skill install --dry-run` resolves paths from a
subdirectory and writes nothing; install then remove round-trips leaving no files behind;
`python -m vqapr --help` matches the console script.

## What this does not do

`run` still discards its result — `cli/run.py` keeps `occurrences` and `account_version` and nothing
else. That is a real gap and it is deliberately still open: the testbed has not yet reached a run, so
nothing has measured what shape a persisted result needs. Building it now would be guessing, and
`docs/handoff/2026-08-24-cli-tier1-rescope.md` records why that ordering is the point.
