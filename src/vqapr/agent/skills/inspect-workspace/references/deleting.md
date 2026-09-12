# Removing things, and reading the refusals as a dependency report

## Survey first

`rm` refuses while a registered run still names the thing — **and the refusal names which run.**
That makes a refused `rm` a useful answer rather than an obstacle: it is the dependency query you
would otherwise have to construct.

The deliberate version of the same query, before deleting anything:

```bash
vqapr list components --reads <dataset-id>    # what would lose its input
vqapr list runs                               # what still names these components
```

## The verbs

| verb | removes |
|---|---|
| `vqapr rm strategy <run-id>/<id>@<fp8>` | one strategy record |
| `vqapr rm datamodel <run-id>/<id>@<fp8>` | one datamodel record |
| `vqapr rm run <run-id> [--keep-latest]` | a run's records |
| `vqapr rm run-definition <run-id>` | the registered declaration, leaving the records |
| `vqapr rm component <id>` | a registered component |
| `vqapr rm dataset <id>` | a registration, and the materialized files behind it |

All of them refuse while a writer may still hold the record.

`rm run-definition` reports the records it left behind and names the verb that removes them, so a
half-cleanup says what is left rather than looking finished.

## `vqapr rm dataset` and the user's own files

On a **materialized** dataset — one a DataModel wrote — it withdraws the registration **and
deletes** the files under `.vqapr/materialized/<id>/`. That is how a datamodel run is retried, and
how a throw-away output is dropped.

On a dataset registered from **the user's own path**, it withdraws the registration and **does not
touch their file.** vqapr deletes only what vqapr wrote.

It refuses while a registered run takes its trading days from that dataset (`schedule.days_from`), naming
the run.

## `--cascade`

```bash
vqapr rm run <run-id> --cascade
```

One gesture: the run's records, its registered definition, the materialized datasets its
datamodels wrote, and the components it named — **keeping, and naming as `kept`, anything another
registered run still names.**

This crosses several kinds and is not reversible. **Show the user what it will take before running
it**, and let them say yes. The single-kind verbs above exist for the step-by-step case, and are
the right choice when the user wants to watch each removal.

`--cascade` exists because deletion has to be easy — a workspace nobody can clean up becomes a
workspace nobody trusts. The `kept` list is what makes it safe to offer: it says what the gesture
declined to take.

## `--keep-latest`

On `rm run`, keeps the most recent record of each component and removes the rest. The usual shape
after a session of tuning, where the earlier records were steps rather than results.

## What a withdrawn definition leaves

`vqapr list runs` keeps showing the run as `status: orphaned` — records with no declaration behind
them. They are still readable, and `show run` still answers from what was frozen. Say "orphaned"
rather than "deleted" when reporting it.

## Resetting a disposable workspace

If there is no result worth preserving:

1. Keep the authored YAML and component files.
2. Before touching anything, obtain approval for the destructive reset from the user.
3. Remove only the project-local `.vqapr/` workspace state.
4. Register the corrected declarations again.

**Never delete source data or authored declarations as part of that reset.**
