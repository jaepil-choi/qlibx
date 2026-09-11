"""Freeze a run's own record to disk while it runs, so a later process can read it.

`recorder_rows` lives in memory for the whole run (`run_state.py:65`). A run that crashes leaves
nothing; a run that finishes leaves nothing anyone else can read. Two things follow, and neither is
a convenience:

- **Parallel execution is impossible.** Five processes running five factors each hold their results
  in their own memory, and nobody can read all five afterwards. That is AC-R4.
- **`show run <id>` has nothing to show.** The only way to answer a question about a finished run is
  to run it again. That is AC-R5.

The layout is argued in `docs/design/run-record-layout.md`; the two decisions that shape this
package are repeated here because they are the ones a reader will otherwise try to "simplify".
The tables are parquet since record `146`; see `PART_SUFFIX`.

**A directory scan, not an index file.** An index would put every concurrent writer on one
atomic-replace target, which is exactly the lost-update the workspace lock exists for
(`workspace.py:53-55`): two processes read, both append, the second write erases the first, and
nothing fails. Each run writes only inside its own directory, so two runs cannot collide.

**The writer appends in chunks.** `append` takes a chunk at a time and never re-reads what it
already wrote, so a caller that streams rows as it produces them gets crash survival and bounded
memory for free. Note what the PRODUCT currently does with that: `public.run` hands over
`recorder_rows` once, after the run returns, so today's records are written in one pass at the end.
The chunked interface is what makes streaming possible later; it is not a claim that the run
streams now.

**Persistence is not the execution layer.** This was `flow/record.py` until campaign M6 Step 3.
Reading a record is what a report, a CLI listing and a second process do, and none of them runs
anything -- so the machinery lives above `flow/` and imports nothing from it. The half that DID
need the engine, because it turns a `SimulationResult` into a record, stayed behind as
`flow/freeze.py`.

Three modules, layered in one direction so the cycle that promotion could have introduced cannot
come back: `schema.py` (what a record is: filenames, models, paths, encodings) is imported by
`reader.py` (what exists, how far it got, the rows back), which is imported by `writer.py`. The
names below are the package's door; everything else is private to the module that holds it.
"""

from __future__ import annotations

from vqapr.record.reader import (
    LOCK_FILENAME,
    LOCK_STALE_AFTER,
    STATUS_COMPLETED,
    STATUS_RUNNING,
    STATUS_UNFINISHED,
    LockClaim,
    RunRecordLive,
    RunRecordMissing,
    datamodel_progress,
    datamodel_refs,
    member_progress,
    read_datamodel_record,
    read_member_record,
    read_record,
    read_run_record,
    read_strategy_record,
    read_table,
    read_typed_table,
    record_address,
    recorded_run_ids,
    remove_run_record,
    remove_strategy_record,
    resolve_strategy_ref,
    run_ids,
    strategy_progress,
    strategy_refs,
    table_ids,
    unfinished_datamodel_refs,
    unfinished_member_refs,
    unfinished_strategy_refs,
)
from vqapr.record.schema import (
    COMPACT_FILENAME,
    DATAMODEL_FILENAME,
    DATAMODEL_KIND,
    DATAMODELS_DIRECTORY,
    PART_SUFFIX,
    RECORD_FIELDS_BY_KIND,
    RECORD_FILENAME,
    RUN_FILENAME,
    RUN_JSON_FIELDS,
    RUN_KIND,
    RUNS_DIRECTORY,
    SCHEMA,
    SPILL_BYTES,
    STRATEGIES_DIRECTORY,
    STRATEGY_FILENAME,
    STRATEGY_KIND,
    TABLES_DIRECTORY,
    DatamodelRecord,
    RunRecord,
    StrategyRecord,
    record_directory,
    record_fields,
    record_path,
    run_record_path,
)
from vqapr.record.writer import (
    RunRecordConflict,
    RunRecordExists,
    RunRecordTaken,
    RunRecordWriter,
    write_run_record,
)

__all__ = [
    "COMPACT_FILENAME",
    "DATAMODELS_DIRECTORY",
    "DATAMODEL_FILENAME",
    "DATAMODEL_KIND",
    "LOCK_FILENAME",
    "LOCK_STALE_AFTER",
    "PART_SUFFIX",
    "RECORD_FIELDS_BY_KIND",
    "RECORD_FILENAME",
    "RUNS_DIRECTORY",
    "RUN_FILENAME",
    "RUN_JSON_FIELDS",
    "RUN_KIND",
    "SCHEMA",
    "SPILL_BYTES",
    "STATUS_COMPLETED",
    "STATUS_RUNNING",
    "STATUS_UNFINISHED",
    "STRATEGIES_DIRECTORY",
    "STRATEGY_FILENAME",
    "STRATEGY_KIND",
    "TABLES_DIRECTORY",
    "DatamodelRecord",
    "LockClaim",
    "RunRecord",
    "RunRecordConflict",
    "RunRecordExists",
    "RunRecordLive",
    "RunRecordMissing",
    "RunRecordTaken",
    "RunRecordWriter",
    "StrategyRecord",
    "datamodel_progress",
    "datamodel_refs",
    "member_progress",
    "read_datamodel_record",
    "read_member_record",
    "read_record",
    "read_run_record",
    "read_strategy_record",
    "read_table",
    "read_typed_table",
    "record_address",
    "record_directory",
    "record_fields",
    "record_path",
    "recorded_run_ids",
    "remove_run_record",
    "remove_strategy_record",
    "resolve_strategy_ref",
    "run_ids",
    "run_record_path",
    "strategy_progress",
    "strategy_refs",
    "table_ids",
    "unfinished_datamodel_refs",
    "unfinished_member_refs",
    "unfinished_strategy_refs",
    "write_run_record",
]
