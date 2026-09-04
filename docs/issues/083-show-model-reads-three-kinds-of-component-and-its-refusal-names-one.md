# 083 — `show model` reads three kinds of component and its refusal names one, as an unhandled TypeError

**Status:** OPEN. Found 2026-09-04 by `kwam-enhanced-index/vqapr-enhanced-index-3` (B3), feeding
the output of `list components` to `show model`. Confirmed in source on this branch.

**Touches:** `src/vqapr/cli/show.py:139-163` (`_model`: `CONSTRAINT` and `DATA_MODEL` are handled by
name, every other kind falls through to `load_strategy_model`);
`src/vqapr/extension/loading.py:63` (`raise TypeError(f"ref must identify a {kind.value}
component")`); `src/vqapr/cli/list_.py` (no `--kind` filter).

## What happens

`vqapr list components` returns one list of every kind — 37 datamodels, 6 strategies, an exchange,
a constraint — with `kind` on each row. Passing that list to `show model` breaks on the exchange:

```json
{"stage": "unhandled", "failures": [], "family": null,
 "error": "TypeError: ref must identify a strategy_model component"}
```

Two things are wrong with that sentence.

**It is false.** `show model` reads three kinds: a constraint (its own branch, reporting `reads`,
`decides`, empty `forms`), a datamodel (`load_data_model`), and a strategy model. The command
immediately before this one in the reporter's session had shown a *datamodel* successfully. A
reader who believes the message concludes that their datamodels cannot be shown — and `show model`
is the most useful interrogation verb the package has (record `149` made it read the model's own
declarations; the reporter singles it out as what let them check thirty alphas' lookback windows
without opening a source file).

**It arrives unstructured.** `_model` is thirty lines from a good refusal: an unregistered id gets
`InputError("cli.input.value_invalid")` naming the registered ids and telling the reader to run
`vqapr list components`. A registered id of the wrong kind gets a raw `TypeError` and an
`unhandled` envelope with an empty `failures` list. The two neighbouring mistakes are the same
mistake, and only one of them is answered.

`loading.py:63` itself is not wrong to say `{kind.value}` — it is a generic loader and the kind it
names is the kind it was asked for. The defect is that `show model` asks for `strategy_model`
whenever the component is not one of the two it recognises, so the loader is answering a question
the CLI framed badly.

## What to do

- `_model` should refuse an unshowable kind itself, with the `InputError` shape it already uses
  next door: name the kind it got, name the kinds it reads, and point at `list components`.
- `vqapr list components --kind <kind>`, so the wrong ref is never assembled in the first place.
  `082` wants a `--reads` filter on the same command.

The fix is small. What it buys is a reader who does not conclude that a working feature is closed
to them.

## Related

`055` (what `show model` reports, closed by record `149`), `057` (a missing record refused by
name), `082` (the `--kind`/`--reads` filters), and the standing rule that a refusal states what is
true.
