# 074 — Two refusals that name the key, and the command

`T6`'s documentation half needs no record. Its two behavioural halves do, and one of them turned
out to be a defect in the machinery that renders every `check` refusal.

## 011.7 — a raw `KeyError` as `observed`

Writing `component_id:` where the run-spec template says `component:` produced:

```
code    : run.check.declaration_invalid
observed: KeyError: 'component'
fix     : correct the run spec at spec.yaml so the declaration phase completes, then check again
source  : {"file": "spec.yaml", "key_path": null, "line": null}
```

A raw Python exception as the observed value, a fix naming no cause, and a null key path. Every
other refusal in the surface names its cause precisely. It cost a first-time user about four
minutes of diffing against a re-emitted template to find one word.

`require_declared_keys` checked only the **top-level** keys; `component` lives inside `strategy:`,
so a mis-keyed nested field passed it and surfaced later from the declaration phase as whatever
Python said. `_NESTED_REQUIRED` now names the keys the readers index directly, and the check
collects across sections, so a spec wrong in two places still costs one command:

```
code    : cli.input.keys_missing
observed: missing 1: strategy.component
fix     : add the missing keys, then retry; `vqapr new run-spec` emits a template naming every
          required key
source  : {"file": ".../spec.yaml", "key_path": "strategy.component", "line": null}
```

## The reason `key_path` was still null, which was a second defect

Naming the key was not enough. `check.py`'s `_from_input` read:

```python
source = FailureSource(file=str(spec)) if carried.file is None else carried
```

with a comment directly above it saying *"a source the error already carried is kept rather than
overwritten — the error knows its own key path, and this only knows the file."* The code does the
opposite: when `file` is absent it replaces the **whole** source, and `file` is absent in exactly
the case where the error carries a `key_path` and no file. So the one field `_from_input` cannot
know was the one it discarded, for every `InputError` that named a key.

It merges now — the error's `key_path` and `line`, with the file filled in. Any refusal that names
a key path has been reaching `check`'s envelope without one; this is not specific to 011.7.

## 011.8 — a Python call in a CLI-only user's fix

`Workspace.open` on a directory with no workspace said:

```
fix: call Workspace.create() to initialize the workspace before opening it
```

to a reader who has only ever typed commands. It now names the CLI path that creates a workspace —
`vqapr register <declaration>.yaml`, which creates one as it registers — the same substitution
`declaration.read` already avoids by naming the file rather than the dict lookup.

**Scoped to that one string.** The two `vqapr.public.register_dataset` strings at
`workspace.py:548`/`:558` are deliberately unchanged and verified byte-identical to `7ae3d3af`.
They fire only on a path that bypasses the CLI — `cli/register.py` already calls that very
function — so they are Python-API-to-Python-API guidance and are correct as written. Rewriting them
to name a CLI verb would misdirect the only reader who can trigger them. Issue `011.8` scopes
itself to the `Workspace.create()` string, and the earlier framing of those two as "propagation"
did not survive measurement.

## What the documentation half corrected, and one number that was backwards

Recorded here because the correction matters even though the edits need no record of their own.

**FRICTION-6 was wrong, and the first draft of this plan would have shipped its error.** The skill
said `check` makes "eight independent judgments"; the envelope returns five names, so the finding
read as an off-by-three. Measured: `CODES` carries exactly **eight** judgments and `_PHASES`
carries exactly **five** phases, one of which is itself named `judgments`. Eight is correct and
pinned by `tests/cli/test_check.py`. The skill now states both numbers and says which one the
envelope shows, because counting `checked` and expecting eight is the obvious mistake.

Also: the roster is named as the sixth declaration a run wants, with what its absence costs;
`krx_rules` and `--profile krx` appear for the first time; `vqapr new constraint` appears with
`project`'s contract quoted; the instruments template names its two required columns and its first
sentence is no longer garbled; the agendas template explains what a 15:29 callback can see and
moves valuation to 15:31 with the reason; and `vqapr new --help` states that component and exchange
kinds write two files.

## Validation

```
uv run pytest tests/ -q      # 1311 passed, 14 deselected
```

Both refusals were driven through the CLI before and after. The documentation edits are checked
mechanically — literal strings in `SKILL.md` and the templates, and `vqapr new --help` through the
parser rather than by reading the source.

The refusal-code baseline was regenerated for line movement only; its drift against `7ae3d3af`
remains the two codes record `068` added, with nothing removed.
