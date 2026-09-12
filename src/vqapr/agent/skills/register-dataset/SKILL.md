---
name: register-dataset
description: Reads the user's own price, fundamental, or signal files (csv, parquet, xlsx, database extracts), interviews the user about what each column means, and writes a vqapr dataset declaration that passes `vqapr register`. Use when the user wants to load, register, import, or connect their data to vqapr, or when a question arises about point-in-time correctness, `available_at`, look-ahead bias, the timezone of a timestamp, universe membership, or whether an instrument was tradable on a given day.
---

# Register a dataset with vqapr

## Invoke the CLI through the active environment

Installing a console script into a virtual environment does not put it on the global shell PATH.
Use one launcher consistently:

- activated environment: `vqapr --help`
- uv-managed project: `uv run vqapr --help`

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed; the environment
is simply not activated. Apply the same prefix to every command below.

## What this skill is for

vqapr does not read the user's spreadsheet, database or vendor extract. It reads parquet that
satisfies a declared contract. Everything between those two — what the columns mean, which
timestamp is defensible, what a flag encodes — is a conversation, and this skill is that
conversation.

**The framework validates schema, keys and duplicates. It cannot detect a look-ahead**, because a
timestamp that is wrong in meaning is still perfectly well-formed. That is why the interview comes
before the first `register`, not after one fails.

## The one rule this skill exists to enforce

Every proposal you make falls in one of two columns, and they are settled differently.

| | examples | who settles it |
|---|---|---|
| **The data proves it** | no column combination is unique → another key axis is needed · four numbers with a fixed ordering → a price bar · a column with six distinct values → a label, not a measurement · a timestamp with no zone → registration will refuse it | **you may settle it** |
| **The name is all you know** | which of the four is the opening price · whether that date is the observation or the publication · whether that boolean means halted · whether a missing row means not listed or not traded | **the user must settle it** |

The lower row is not falsifiable from the values. Swap the open and the close and both still sit
between the high and the low; a daily bar shifted nine hours still has a valid timezone-aware
schema. So: **do not infer a convention from a column name**, and where the answer is not in the
data or its documentation, say it is unknown and let the user decide.

## Workflow

Copy this checklist and check items off as you go.

```
Registration progress:
- [ ] 1. Read the source with your own tools and profile it
- [ ] 2. Split the findings into proven and must-ask
- [ ] 3. Get the user's answers on the must-ask column
- [ ] 4. Choose the grain
- [ ] 5. Prepare the parquet, and prove the timezone on one known instant
- [ ] 6. Write the declaration and register it
- [ ] 7. Confirm, and record what the package could not check
```

### 1. Read the source and profile it

**Read the user's source with your own tools, not with vqapr.** The source may be xlsx, csv, a
database extract, or something nobody described; vqapr reads none of those, and adding a reader
for them to the package is the thing this division exists to avoid.

Run the profiler that ships beside this file. `<skill>` is the directory this `SKILL.md` is in —
`.agents/skills/vqapr-register-dataset/` or `.claude/skills/vqapr-register-dataset/`, depending on
which target installed it:

```bash
uv run python <skill>/scripts/profile_source.py <path>          # human-readable
uv run python <skill>/scripts/profile_source.py <path> --json   # for further work
```

It needs duckdb, which vqapr already depends on, so the environment that has vqapr can run it.

It reports only the upper row of the table above: unique key candidates, inequalities that hold
on every row, timezone-awareness and the wall clocks a timestamp actually lands on, low-cardinality
labels, null shares, and per-name first/last observation. It reads csv, tsv, parquet and parquet
directories. A spreadsheet is refused rather than half-read: converting one is a decision about
merged cells and formatting, so do it deliberately and profile the result.

### 2. Split the findings

Present both columns to the user in one message. Show **their own rows** — the profiler's samples,
not invented examples — so the question is about data they recognise.

### 3. Get the answers

`available_at` is the one that decides whether the results mean anything. See
[references/point-in-time.md](references/point-in-time.md) for what to ask and why each answer
matters. The price columns are in [references/price-axis.md](references/price-axis.md); listing,
delisting and halts are in
[references/universe-and-tradability.md](references/universe-and-tradability.md).

**Do not proceed on a guess.** An unconfirmed `available_at` produces a registration that passes
every check and a backtest that is quietly reading the future.

### 4. Choose the grain

`grain` says what one row IS, and it decides both how the data is read and what it costs. A
date × ticker table is `instrument_instant`. The vendor's long table with several rows per name
and date is `rows`. See [references/grain-and-cost.md](references/grain-and-cost.md) — it carries
the measured costs of both and the case for registering a vendor table twice.

### 5. Prepare the parquet, and prove the timezone

Registration does not convert a naive timestamp for you: only the user knows which instant a value
means, and a wrong localization is a silent point-in-time leak rather than an error.

Before converting the whole file, round-trip **one known instant** through the exact preparation
code — [references/timezone-proof.md](references/timezone-proof.md). Casting a naive pyarrow
timestamp to `timestamp(..., tz="Asia/Seoul")` preserves the epoch value and changes only how it
displays; it does not mean "read this wall clock as Seoul time."

While preparing, watch for calculations that make one row's value depend on another row's
observation — moving averages, cumulative sums, ranks, resampling. vqapr does not forbid them and
could not, but they belong in a DataModel where they are reviewable:
[references/discouraged-preparation.md](references/discouraged-preparation.md).

Prepare a genuinely absent value as `NULL`, which reads as a missing observation. A NaN or an
infinity is refused at registration or never — reads trust what registration accepted, so one that
gets through reaches a model and propagates through every number it touches while the run still
reports a result.

### 6. Write the declaration and register it

```bash
vqapr new dataset --out prices.yaml    # a template with every required key and its meaning
vqapr register prices.yaml
```

**Fill in the template rather than hand-writing the YAML.** It is generated from the contract the
package actually enforces, so it cannot drift from it; this file deliberately does not repeat its
key list.

A dataset and its source file register together — `source_id` and `path` are declared inline, and
the path resolves relative to the YAML.

`field_types` is a declaration the user makes and registration checks **once**, against the file:
one of `TIMESTAMP_TZ`, `DATE`, `INTEGER`, `DOUBLE`, `VARCHAR`, `BOOLEAN`. A `DECIMAL` column is
refused — cast it to `DOUBLE` while preparing — so a model reads one numeric type per field and
`Decimal` never arrives from a dataset.

### 7. Confirm, and record what the package could not check

```bash
vqapr list datasets
vqapr show dataset <id> --limit 20
```

`show dataset` returns the **declared projection** — the fields you named, holding the values a
model will receive (`items_are: "projection"`) — so for an aggregated registration this is where
you see whether the expressions did what you meant. On a large file that evaluates the whole
grouping once; `--source` shows the file's own rows instead.

Then **write down, for the user, the facts that change what the result means and that vqapr cannot
verify**: which instant `available_at` was taken to be, whether a fill price is observable at the
time it is used, and what a derived tradability rule does not cover. These belong in the result's
limitations, not in a new validation — widening the package's judgment here would create a
guarantee that is only half true.

## Correcting a registration

Registering the same id again replaces it in place, with no flag; there is no `register --force`.
A `runs:` declaration is the exception. See
[references/correcting-a-registration.md](references/correcting-a-registration.md).

## Stop condition

`vqapr register` accepted the declaration with no failures, `vqapr list datasets` shows the id, and
every question in the must-ask column has an answer the user gave. A dataset registered with an
unconfirmed `available_at` has not finished this skill.

---

A refusal carries its own status, stage and cause, plus `fix`, `requirement`, `observed` and
`source` — read it rather than looking for it here. Status **500 is a vqapr defect**: do not work
around it, report it with the envelope. **502 is your own code raising** — `cause.origin` is
`"user"` and `cause.where` is your file and line; fix the component. **503 is the machine** — retry
unchanged.
