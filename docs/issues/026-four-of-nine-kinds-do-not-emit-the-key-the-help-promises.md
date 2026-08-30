# 026 — `new --help` promises a `declaration` key that four of nine kinds do not emit

**Status:** **closed** by
`docs/implementations/096-every-new-kind-says-how-to-use-its-file.md` (branch
`fix/026-declaration-key-on-every-kind`). `dataset`, `agendas` and `execution-input` now emit
`declaration`. `run-spec` emits `registrable: false` instead, because a run spec genuinely cannot
be registered - `vqapr register` refuses it with `declaration.read.unknown_section`. The help was
overpromising rather than the envelopes underdelivering, and it now states what is true.

**Status when filed:** open. Found 2026-08-30 by the final first-time-user journey in
`kwam-enhanced-index/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-001**,
`papercut`, ~2 minutes.
**Touches:** `src/vqapr/cli/new.py:275-281` (the help text), and the `template.new` envelopes at
`new.py:394`, `:441`, `:612`.

## What the help says

Of the positional `kind` argument:

> Component and exchange kinds write TWO files: the .py named by `--out`, and the .yaml beside it
> that registers it. **Every kind reports the file to hand `vqapr register` as `declaration`**

The reporter read that as a guarantee across all nine kinds and planned to script off it.

## What arrives

Only the kinds that write two files emit it. The single-file kinds report `path` only:

```
$ vqapr new dataset --out declarations/dataset.yaml
{"kind": "dataset", "ok": true, "path": "declarations\dataset.yaml", "stage": "template.new"}

$ vqapr new instruments --out declarations/instruments.py
{"declaration": "declarations\instruments.yaml", "kind": "instruments", "ok": true,
 "path": "declarations\instruments.py", "stage": "template.new"}
```

`dataset`, `run-spec`, `agendas` and `execution-input` — four of the nine kinds — have no
`declaration` key at all.

Confirmed here: the component path (`new.py:394`) and the exchange path (`new.py:612`) pass
`declaration=`; the dataset path (`new.py:441`) and its single-file siblings do not.

## Why it is worth filing

Harmless in this journey, because the reporter was reading the output by eye — and they noticed only
because they diffed the five envelopes against each other. But the sentence is *the reason someone
writes the script*, and a script that trusts it raises `KeyError` on four kinds out of nine.

The help's own preceding clause is the tell: it has just finished explaining that component and
exchange kinds write two files and the others write one, and then claims a key that only the
two-file kinds emit. The distinction is stated and then contradicted in the same paragraph.

## What closes it

Either:

- emit `declaration` on every kind, aliasing `path` for the single-file ones — so the sentence
  becomes true and the script becomes writable; or
- narrow the sentence to *"component and exchange kinds report the file to hand `vqapr register` as
  `declaration`; the rest report it as `path`"*.

The first is better if anything is expected to script over `vqapr new`, and the envelope is the
package's contract with exactly that reader.
