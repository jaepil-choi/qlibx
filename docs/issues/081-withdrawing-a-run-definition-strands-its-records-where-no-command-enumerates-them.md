# 081 — withdrawing a run definition strands its records where no command enumerates them

**Status:** OPEN. Found 2026-09-04 by `kwam-enhanced-index/vqapr-enhanced-index-3` (B1), deleting
one discarded alpha from a workspace and timing what it took. Confirmed in source on this branch.

**Touches:** `src/vqapr/cli/list_.py:342-353` (`list runs` enumerates `workspace.run_definitions`
and attaches `recorded` to each), against `src/vqapr/flow/run_records.py:920` (`run_ids`, which
enumerates the records themselves and is called by `rm` but by no `list`);
`src/vqapr/cli/rm.py:1-14` (the module docstring stating that withdrawal and removal do not reach
across).

## What happens

Removing one alpha completely takes five commands, in an order the surface does not state:

```
vqapr rm run-definition alpha-price-010
vqapr rm dataset        alpha-price-010-values
vqapr rm component      alpha-price-010
vqapr rm datamodel      alpha-price-010/alpha-price-010@630ad5b6   <- the record
vqapr rm run            alpha-price-010                            <- record.json
```

`rm`'s refusals are exemplary at every step — they name what is holding the id and what to do
first — and following them is what produces the defect. After step 1,
`vqapr list runs --id alpha-price-010` returns **0 rows**, while
`vqapr list datamodels --run alpha-price-010` still returns an 18,067-row record. The record is
intact and readable; it is simply no longer reachable by anyone who does not already know the run
id, because `list runs` walks the registered definitions and the definition is gone.

`rm run` needs that id. So the state the refusals walk you into is one where the remaining cleanup
step can only be performed from memory.

## Why this is not what the docstring promises

`cli/rm.py` states the design and it is a good one:

> Neither reaches across: withdrawing a registration leaves its records readable (a finished run
> pins what it used inside its own record), and removing records leaves the run registered to run
> again.

Readable is true. **Findable is not**, and readable-but-unfindable is not a state anybody chose:
`run_ids(store_root)` already enumerates every run directory holding a record, and `rm` calls it.
No `list` does.

## What to do

Any one of these closes it; the first is the smallest.

- **`list runs` reports orphans.** Union the registered definitions with `run_ids(store_root)`, and
  mark a run with records and no definition — `definition: null`, or `status: orphaned`. The
  entry point then survives the withdrawal, which is the only thing actually missing.
- **`rm run-definition` says what it left.** Its success payload should carry the records that
  remain and the command that removes them: *"3 record(s) remain for 'alpha-price-010'; remove them
  with `vqapr rm run <id>`"*. `rm dataset` already does this well in the other direction — it
  reports the materialized output it deleted and leaves a dataset at the author's own path alone.
- **A `--cascade` on `rm run`.** The heaviest option and the one that needs an owner ruling, since
  it deletes evidence in one gesture.

Five steps for one deletion is defensible on its own — a registration is an identity and a record
is evidence, and they are genuinely different things. The order being undiscoverable is the part
worth fixing after the above: the refusals name the next step, so a payload naming the whole
remaining set would finish the job.

## Related

`060` (`rm dataset`, the kind the skill promised and the CLI lacked), record `139` (`rm` and
`Workspace.remove`), `082` (the other half of the same reverse-lookup gap).
