---
name: inspect-workspace
description: Answers what a vqapr workspace already holds and removes what is no longer wanted — listing datasets, components, and run records, showing what a frozen run used, judging whether a stored result can be reused instead of recomputed, and cascading deletes. Use when the user asks what is registered, what a run depended on, whether something can be reused, or wants to clean up runs and registrations.
---

# Answer questions about a vqapr workspace

## Invoke the CLI through the active environment

Installing a console script into a virtual environment does not put it on the global shell PATH.
Use one launcher consistently:

- activated environment: `vqapr --help`
- uv-managed project: `uv run vqapr --help`

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed; the environment
is simply not activated. Apply the same prefix to every command below.

## The job is translating a question into a filter

The CLI already carries the filters. What it does not carry is which one answers the question the
user actually asked, and that is what this skill is for.

| the user asks | the command |
|---|---|
| "what have I registered?" | `vqapr list <kind>` — one kind per call |
| "what reversal strategies did I write?" | `vqapr list components --kind strategy --id reversal` |
| "what breaks if I delete this dataset?" | `vqapr list components --reads <dataset-id>` |
| "which runs breached a compliance rule?" | `vqapr list strategies --run <id> --failed-contract` |
| "what did that run actually use?" | `vqapr show run <run-id>` |
| "where did this number come from?" | `vqapr show strategy <run-id>/<ref> --table <t>` |
| "can I reuse this instead of re-running?" | [references/reuse-judgement.md](references/reuse-judgement.md) |
| "clean this up" | [references/deleting.md](references/deleting.md) |

`--reads` is the one worth knowing about: it **loads each component and asks it** which datasets
its `inputs()` names, so it answers a dependency question from the code rather than from a
convention.

## `list` takes exactly one kind

`kind` is a required positional and there is no all-kinds form — bare `vqapr list` is refused
with `usage.rejected`. So surveying a workspace is one call per kind:

```
vqapr list datasets
vqapr list sources
vqapr list components
vqapr list instruments
vqapr list runs
```

A kind you registered nothing under returns `count: 0`, which is an answer rather than a failure.
An empty or uninitialised directory reports zero items and succeeds.

The remaining kinds are per-run: `vqapr list strategies --run <run-id>` and
`vqapr list datamodels --run <run-id>`.

## The filters

| flag | on | what it does |
|---|---|---|
| `--id` | any kind | substring match on the declaration's identity |
| `--kind` | `components` | keep one component kind, spelled as `new` and `register` spell it |
| `--reads` | `components` | keep the components whose `inputs()` names this dataset id |
| `--run` | `strategies`, `datamodels` | which run's records |
| `--strategy` / `--fingerprint` | records | narrow to one component or one version of it |
| `--failed-contract` | `strategies` | only records whose compliance contract failed |
| `--since` | records | only records after an instant |

## Records are found by scanning

There is no index file — which means no shared target for concurrent runs to lose each other's
entries on. A consequence worth knowing: `list runs` keeps showing a run whose **definition was
withdrawn** but whose records remain, as `status: orphaned`.

Other statuses that are answers rather than problems:

- `status: running` — the run still holds the lock; `chunks` and `last_event_time` come from a
  progress file rewritten every few seconds and can lag that much
- `status: unfinished` — the lock has been quiet for two minutes and no record was written: the
  strategy was killed, or its flow ended in a refusal

## Counting

**Count records, not directories.** Rows with `status: completed` are how many times a component
ran to completion. Counting directories over-counts by the crashes, because a killed run leaves a
directory with rows and no record.

## Reading one thing

```bash
vqapr show run <run-id>                              # the configuration every strategy shared
vqapr show strategy <run-id>/<id>@<fp8>              # one strategy's output
vqapr show strategy <run-id>/<ref> --table <t> --limit 1000 --instrument <id>
vqapr show datamodel <run-id>/<id>@<fp8>
vqapr show dataset <id> --limit 20
vqapr show model <id>                                # what a component declares it reads and does
```

`<run-id>/<strategy-id>` without the fingerprint works when exactly one record of that strategy
exists.

**`rows_total`, `matched` and `returned` are reported separately**, so a truncated page never reads
as a short run. Quote the right one; `--limit N` returns at most N rows and `0` returns none, so a
whole table is `--limit <rows_total>`.

`show dataset` returns the **declared projection**: `items` holds the fields the registration
names, with the values a model reading it receives, and `items_are: "projection"` says so. For an
aggregated registration that evaluates the whole grouping — a full pass over a large file — which
is the cost of confirming the reduction rule. `--source` returns the file's own rows and columns
instead (`items_are: "source"`); `source_rows_total` is always the file's count.

A dataset a run wrote names its producer twice: `produced_by` is the run id, `produced_by_record`
is the record `<id>@<fp8>` — the component **version** that wrote it. When that version is not the
one registered now, `vqapr check <run-id>` reports `run.output_stale`; the parquet is not what the
file on disk would compute.

Everything here reads what was **frozen to disk**. Nothing is recomputed — re-running to answer a
question about a run would be a different run.

## Before recomputing, check whether you have to

A stored result can often be used directly. The check is not "does the file exist":
[references/reuse-judgement.md](references/reuse-judgement.md) lists what a consumer must match
before reuse is honest.

## Removing things

Deletion is meant to be easy, and it is — but only after the survey. Removing something a
registered run still names is refused, **and the refusal names the run**, which makes `rm` a
dependency report as well as a verb. [references/deleting.md](references/deleting.md).

## Stop condition

The user has the answer with the identifiers they need for the next command, and any number quoted
from a truncated page was quoted as `rows_total` rather than `returned`.

---

A refusal carries its own status, stage and cause, plus `fix`, `requirement`, `observed` and
`source` — read it rather than looking for it here. Status **500 is a vqapr defect**: do not work
around it, report it with the envelope. **502 is your own code raising** — `cause.origin` is
`"user"` and `cause.where` is your file and line; fix the component. **503 is the machine** — retry
unchanged.
