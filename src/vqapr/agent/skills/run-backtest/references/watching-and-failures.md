# While a run executes, and when a strategy fails

## A record is written last

`strategy.json` lands when the strategy finishes. Until then there is a directory with rows in it
and no record, and `vqapr show strategy` will not read it — that verb reads finished records only.

`vqapr list strategies --run <run-id>` is the verb for a run in flight:

| field | what it says |
|---|---|
| `status: running` | the run still holds the lock |
| `chunks` | sessions accepted so far |
| `last_event_time` | the last session it accepted |
| `lock.refreshed_ago` | seconds since the run last touched the lock |

`chunks` and `last_event_time` come from a progress file the run rewrites every few seconds, so
they can lag by that much. A number that has not moved in ten seconds is not evidence of a hang.

## `unfinished` is not `running`

A directory whose lock has been quiet for two minutes and still has no record is
`status: unfinished`. The strategy was killed, or its flow ended in a refusal — **the run's own
envelope says which**, so read that rather than guessing from the directory.

`vqapr rm strategy <run-id>/<ref>` removes such a directory.

## Rows survive more than you would expect

Rows stay in memory while the run executes and land once, when it ends — normally, through an
exception, or through Ctrl+C, all three of which keep every row recorded up to that point.

Only a **hard kill** (`taskkill /F`, an OOM kill) loses rows, and then only what came after the
last spill: a part is written whenever the buffer passes 256 MB. The same line bounds what the rows
cost in memory: the buffer never holds more, and the fold into one file at the end reads the parts
back a row group at a time. It is not the whole of a run's memory — see the sizing paragraph in the
skill.

## When one run in a batch fails

A run is one model with its own account. A refusal inside one — `decide()` raised, or the
`Rebalance` it returned was outside its budget — is that run's outcome, not the batch's.

The envelope is `ok: false`, `stage: run.strategy_failed`, with every run of the batch listed:
`status: completed` lines beside the failed run's block carrying its `stage`, `component_id`,
`failures` and `at`.

The top-level `failures` gathers the failed run's entries. Read `fix` first. `source` names the
strategy and, for a raise from the user's own file, the file and the line.

**The completed records stand.** Fix the failed strategy, register the file again, and:

```bash
vqapr run <run-id>
```

runs that one alone into a new record. The shape is the same under `--jobs N`.

## Reporting this to the user

An `ok: false` batch is not "the backtest failed" when four of five runs completed. Say which
completed and which did not, and that the completed records are readable now.
