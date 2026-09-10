# The sample journey, step by step

```bash
vqapr new sample --out ./first-run
```

## What it wrote

A complete journey the product runs as it stands:

- a **five-day reversal strategy**
- a **venue**
- a small **synthetic panel** — ten names over three years of real KRX sessions
- `sample.yaml` — the one declaration that registers all of it

It is not a starter layout and there is no hidden built-in alpha. It is a reference journey, and it
is not created in a project that did not ask for it.

## The data is synthetic, and the panel is deliberately awkward

Prices and names are made up, so **draw no conclusion about a market from it**.

The panel is **unbalanced on purpose**: one name lists late, one stops trading early. That is what
a real panel looks like, and a sample that was neatly rectangular would teach the wrong shape —
`current()` versus `latest()`, coverage failures, and the tradability question all only appear on a
panel like this one.

## The four commands, and what each answers

```bash
vqapr register ./first-run/sample.yaml
```

Registers the two datasets (the prices and the venue table) with their sources, the exchange and the components — in
dependency order, so the document cannot fail for the order it was typed in. Follow with
`vqapr list datasets` and `vqapr list components` to see what arrived.

```bash
vqapr check sample-run
```

Proves the run without executing it, and **writes nothing**. Its `checked` list has four phases;
the eight judgments happen inside the one named `judgments`. Counting the list and expecting eight
is the usual mistake.

```bash
vqapr run sample-run
```

Preflights, freezes and executes. Success is `ok: true` with a `strategies` map: `status:
completed`, an `occurrences` count, an `account_version` and a `record` — `<strategy-id>@<fp8>`.

```bash
vqapr show run sample-run
```

The configuration every strategy shared: instruments, period, venue, the execution dataset and the fill
convention, initial account, the datasets read and their source digests, and `recorded` — the
records the store holds.

## What to look at next

```bash
vqapr show strategy sample-run/<record> --table vqapr.fill --limit 1000
vqapr show strategy sample-run/<record> --table vqapr.account --instrument _ACCOUNT
```

The first is every fill with its cost; the second is the NAV series. Both are the tables every run
records, and reading them here — on data whose answer does not matter — is the cheapest place to
learn their shape.

For the numbers a report needs, `strategy_report` reads the same record and computes them once;
that is the `analyze-result` skill.

## Then copy it

`sample.yaml` is the thing to copy when writing a first real declaration. It is a filled-in
example of the same document `vqapr new dataset` and `vqapr new run` emit as blanks, and seeing one
filled in answers questions the blanks raise.

The data behind it is not the thing to copy. Registering the user's own source is the
`register-dataset` skill, and it starts with reading their file rather than with this YAML.
