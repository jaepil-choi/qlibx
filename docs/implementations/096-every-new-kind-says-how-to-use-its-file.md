# 096 — Every `vqapr new` kind says how to use the file it wrote

**Closes:** `docs/issues/026-four-of-nine-kinds-do-not-emit-the-key-the-help-promises.md`.
**Branch:** `fix/026-declaration-key-on-every-kind`.

## Why this change exists

`vqapr new --help` promised, of the positional `kind` argument:

> Component and exchange kinds write TWO files: the .py named by `--out`, and the .yaml beside it
> that registers it. **Every kind reports the file to hand `vqapr register` as `declaration`**

Four of the nine — `dataset`, `run-spec`, `agendas`, `execution-input` — reported `path` only. The
reporter read the sentence as a guarantee across all nine and planned to script off it.

## The promise was wrong in both directions

Fixing this by emitting `declaration` everywhere was the obvious move and would have been wrong.
**A run spec is not registrable.** Checked rather than assumed:

```
$ vqapr register spec.yaml
{"stage": "declaration.read", "ok": false,
 "failures": [{"code": "declaration.read.unknown_section",
   "requirement": "a declaration may contain: instruments, datasets, execution_inputs, agendas,
                   components, strategy_configs, valuation_configs, monitoring_policies"}]}
```

A spec **names** components rather than declaring any; `vqapr run` is what takes it. So one of the
four kinds that did not emit the key could not honestly emit it, and the help had been overpromising
rather than the envelopes underdelivering.

## What changed

The envelope now answers the question the caller actually has — *what do I do with this file?*

- `dataset`, `agendas`, `execution-input` emit **`declaration`**. For a single-file kind the
  template **is** the declaration, so it equals `path`; reporting it anyway is what lets a caller
  read one key across kinds instead of branching on which happen to write two files.
- `run-spec` emits **`registrable: false`** and no `declaration`. A caller branches on a field
  rather than on a hard-coded list of kind names it has to keep in sync.
- The help says what is true: every **registrable** kind reports `declaration`, and `run-spec`
  reports `registrable: false` because it is handed to `vqapr run`.

## Validation

**Gate:** `test_all` (scaffold envelopes) + `tests/cli/test_envelope.py` +
`tests/cli/test_commands.py` + `tests/characterization/test_refusal_codes.py`.

| check | result |
|---|---|
| `tests/cli/test_every_new_kind_says_how_to_use_its_file.py` (new) | 13 passed |
| `test_envelope.py` + `test_commands.py` + `test_refusal_codes.py` | 37 passed |
| **full suite, all marks** | **1410 passed, 0 failed**, 570.92s |

The refusal-code baseline needed **no** regeneration: no codes were added or moved.

The merge condition asked that a script reading the key across all nine kinds raise no `KeyError`,
and that loop is the test — `test_a_script_can_read_one_field_across_every_kind` writes exactly the
loop the reporter planned and asserts eight registrable declarations plus one that is not.

Three tests guard the parts that would rot:

- **A tenth kind cannot be added silently.** `test_all_nine_kinds_are_covered_by_this_test` reads the
  parser's own `choices` and requires the parametrised list to match, so a new kind fails here rather
  than quietly skipping coverage.
- **`registrable: false` cannot become a lie.** The premise is re-checked by actually running
  `vqapr register` against a generated run spec and requiring it to fail. If `register` ever learns
  to take one, this fails instead of the envelope going stale.
- **The help cannot drift back** to promising the key for every kind.
