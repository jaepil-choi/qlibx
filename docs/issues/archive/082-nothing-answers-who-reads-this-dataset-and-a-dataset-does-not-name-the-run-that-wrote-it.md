# 082 — nothing answers "who reads this dataset", and a dataset does not name the run that wrote it

**Status:** **CLOSED 2026-09-05 -- record `160` (one-shape campaign Step 5, M5e).**
`vqapr list components --reads <dataset-id>` keeps the strategies, datamodels and constraints
whose `inputs()` name the dataset, each row carrying `reads: {<dataset>: [<fields>]}` -- by
loading every component in this one process, which is where the 36 seconds went (41 process
starts, not 41 loads); no index and no new field. And a materialized dataset carries
`produced_by`, the run that wrote it, set by `DataModelOutput.register` from the run it serves
and reported by `show dataset` and `list datasets`; a dataset from the author's own file names
no run. The `--kind` filter landed earlier with record `156` (`083`).

**Status when filed:** OPEN. Found 2026-09-04 by `kwam-enhanced-index/vqapr-enhanced-index-3` (B2), measured
at 36.3 seconds and 41 processes per question, on a workspace of 40 components. Confirmed in source
on this branch.

**Touches:** `src/vqapr/cli/list_.py:52-58` (`_ACCESSORS` and `--id`, a substring filter over
`_summarize`'s identity fields), `:65-90` (`_summarize`, which for a component reports
`component_id`, `kind`, `fingerprint`, `object_name` and nothing about what it reads);
`src/vqapr/cli/show.py:114` (`_model`, the forward answer, which is complete and good).

## What happens

`vqapr list <kind> --id <substring>` matches identifiers only.

```
vqapr list datasets   --id alpha-revision   -> 10. correct
vqapr list components --id valuation        -> 0.  the 14 components that READ valuation-daily
                                                   are not found
```

`vqapr show model <id>` answers the forward question completely — alias, dataset, fields, lookback,
all of it (record `149` made it read the model's own declarations). The reverse question has no
verb, so it is a full scan:

```
list components (40) -> show model on each -> keep those whose reads name 'valuation-daily'
= 41 processes, 36.3 seconds, per question
```

The answer was right. The cost is linear in the workspace and this is a question research asks
constantly: *what breaks if I change this dataset*, *do these fifteen alphas actually read
different sources*. At 30 alphas it is 36 seconds; at 100 it is two minutes.

The workspace already holds the answer. `inputs()` is evaluated at registration, so what each
component reads is known before any of this is asked — it is simply not indexed or exposed.

## The same gap in the other direction

**A dataset does not name the run that produced it.** `vqapr show dataset <id>` reports
`source_id: materialized-<dataset-id>` and stops: no `run_id`, no `produced_by` (the string appears
nowhere in `src/`). `vqapr list datamodels --run <x>` requires the run id you are trying to find.

The reporter could guess, because they name a run and its output dataset from the same stem — but
that is their convention, not something the framework guarantees, and `output_source_id` deriving
`materialized-<dataset_id>` is a naming rule, not a provenance link. A workspace assembled by two
people, or by a scaffold, has no such stem.

## What to do

- **`vqapr list components --reads <dataset-id>`**, and a `--kind` filter beside it (`083` wants
  the second one too). Both are answerable from what registration already evaluated.
- **`show dataset` names its producer.** For a materialized dataset the run that wrote it is known
  at registration time — `DataModelOutput.register` is called by that run. Carrying `run_id` into
  the registration turns a guess into a fact and gives `081`'s orphan case an entry point as well.

Neither is a defect in behaviour. Both are the difference between a workspace you can interrogate
and one you scan.

## Related

`055` (`show model` reading attributes nothing set, closed by record `149` — this is the reverse of
the question it now answers), `081` (records unreachable once their definition is withdrawn),
`023`/`027` (what a registration records about a source).
