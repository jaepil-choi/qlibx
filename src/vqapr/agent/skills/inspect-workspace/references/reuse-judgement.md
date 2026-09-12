# Can this stored result be used instead of recomputed?

## The question is not "does the file exist"

A stored signal, model prediction, alpha weight, ensemble result or intended portfolio can be used
**without re-running its producer** — but reuse is not a path copy. The consumer has to check that
what it needs matches what was produced.

## What the consumer checks

- **the artifact's schema and semantic type** — the same columns is not the same meaning
- **time, axis, universe and currency compatibility** — a monthly panel is not a daily one, and a
  KRW book is not a USD one
- **the input and producer fingerprints** — which code, over which data
- **path dependency and actual-state dependency** — a result that depended on an account is a
  result about *that* account
- **terminal status and coverage** — a run that ended early covers less than its declared period
- **parent and member lineage** — an ensemble's members have to be the ones you think they are

If identity and compatibility line up on all of that, reuse is honest. If any of it does not, the
result is about a different question and re-running is the cheaper mistake.

## The two that get skipped

**Path dependency.** A turnover-aware strategy, a stop-loss, an adaptive weighting — these read the
account, so their output is a fact about the book that existed then. Reusing one under a different
starting account produces a number with no referent. The result records that it was
path-dependent and which state it saw, which is what makes the reuse checkable at all.

**Coverage.** A record whose run ended in a refusal partway through still holds every row up to
that point, and those rows are real. They are just not the period the declaration asked for. Check
the terminal status before treating the record as complete.

## Where the evidence is

```bash
vqapr show run <run-id>          # datasets read, their source digests, the frozen configuration
vqapr show strategy <run-id>/<ref>   # the component and its fingerprint, registered and as loaded
vqapr list strategies --run <run-id> # status per record
```

`run.json` carries the sha256 of every source the run read. When someone asks later what went into
a result, that is the answer.

## Failed research is worth keeping

Successful trials alone repeat the same failures and the same hypotheses. Failures, unsupported
results, diagnostics and the decisions a user made are all in the catalogue on purpose, and a new
study should look before it starts:

- is there already a similar signal, transform or hypothesis?
- which datasets and operations did it use?
- what is its correlation, overlap and incremental contribution against the existing alphas?
- what failed, and which capability was missing?
- can any of it be reused without re-running?

That last question is this file. The four before it are why the workspace is worth surveying at
all.
