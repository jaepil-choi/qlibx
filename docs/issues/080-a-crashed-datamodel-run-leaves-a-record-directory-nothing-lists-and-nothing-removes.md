# 080 — a crashed datamodel run leaves a record directory nothing lists and nothing removes

**Status:** OPEN. Found 2026-09-04 by `kwam-enhanced-index/vqapr-enhanced-index-3` (A5), counting
how many times each of thirty alphas had been tuned. Confirmed in source on this branch.

**Touches:** `src/vqapr/flow/run_records.py:1046` (`datamodel_refs`, which keeps only directories
holding `datamodel.json`), against `:936` `strategy_refs` and `:966` `unfinished_strategy_refs`
(the strategy side, which has both); `src/vqapr/cli/list_.py:215` (`_datamodels`, no unfinished
pass) against `:145` (`_strategies`, which has one); `src/vqapr/cli/rm.py` (`rm datamodel` resolves
a member record, so a directory without one is not a target).

## What happens

A datamodel run that dies inside a callback leaves its directory behind:

```
alpha-revision-010@8e6a2fe3/tables/      <- no datamodel.json; the run that crashed
alpha-revision-010@119fdc25/datamodel.json
alpha-revision-010@f2e20ddc/datamodel.json
```

Three directories, two runs. `vqapr list datamodels --run <id>` shows the two, which is right.
Nothing shows the third, which is not: it is not listed, `rm datamodel` cannot name it (there is no
record to resolve), and `rm dataset` does not reach it (the output was never registered). It is
removable only with `rm -rf` on a path the CLI never printed.

Record `074` settled this exact question for strategies: a directory with no `strategy.json` is
`running` while its lock is fresh and `unfinished` once it is stale, `unfinished_strategy_refs`
enumerates them and `list strategies --run` shows them with `chunks` and `last_event_time`. The
datamodel side got `datamodel_refs` (record `148`) and neither of the other two.

## Why it matters more than a stray directory

The skill sells the directory count as the tuning history — *"Tweaks are directories"* — and that
is exactly how the reporter used it: `pool.py::tuning_history` counts members to say how many
revisions an alpha has been through. Counting directories over-counts by the number of crashes, so
**a tuning that never produced anything is indistinguishable from one that did** unless the reader
opens each directory. They worked around it by counting `datamodel.json` files, which is what
`datamodel_refs` already does — the surface just never offered it as the count.

The asymmetry is also a live trap for the next reader: `074`'s guarantee is stated in the skill for
strategies, and a datamodel run looks like a strategy run from the outside.

## What to do

The strategy side is the design; make the datamodel side the same shape.

- `unfinished_datamodel_refs` plus a `datamodel_progress`, and an unfinished pass in
  `cli/list_.py::_datamodels` reporting `status: running` / `unfinished` with `chunks` and
  `last_event_time`. `STATUS_*` in `run_records.py` already documents the three states in prose
  that never says "strategy".
- `rm datamodel <run>/<ref>` should accept a directory with no record, since that is precisely the
  one a reader wants to remove.
- Whether a refused datamodel run should clean up after itself is a separate question and probably
  no: the partial chunks are evidence, and `DataModelOutput.open` already clears the *output*
  directory on retry. What is missing is the report, not the deletion.
- The skill's "Tweaks are directories" paragraph should say *count records, not directories*.

## Related

`074` (the strategy half, closed by record `150`), record `148` (datamodel records), `060` (`rm`
lacking a kind the skill promised).
