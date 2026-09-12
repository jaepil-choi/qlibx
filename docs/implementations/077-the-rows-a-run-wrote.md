# 077 — The rows a run wrote

`RunRecorder` writes evidence tables on every run. `show run` reported how many rows each held.
Nothing could read one back.

So a reader learned that `vqapr.fill` held 64 rows and had no way to see one. The only route was
knowing the on-disk layout — `.vqapr/runs/<id>/tables/<name>.jsonl` — and opening the file by hand,
which is exactly the kind of internal knowledge this surface exists to make unnecessary. Both
first-time-user journeys ended up doing it.

This is the same gap `list instruments` closed for the roster sidecar, one artifact along.

## Wiring, not new machinery

`flow/run_records.py` already had both halves: `read_table(root, run_id, table_id)` streams a
table's rows, and `table_ids(root, run_id)` lists what a run recorded. Neither had a caller in the
CLI.

```
$ vqapr show run r1 --table vqapr.fill
{"ok": true, "stage": "run.table", "run_id": "r1", "table": "vqapr.fill",
 "rows_total": 2, "returned": 2, "tables": [...], "items": [...]}
```

`--limit` defaults to 100, and `0` returns every row. **`rows_total` and `returned` are separate
fields** — reporting only `len(items)` would let a reader conclude a run wrote 100 rows when it
wrote 40,000, and a truncated page that reads as a short run is worse than no page.

A mistyped table names the ones this run actually recorded, the way a mistyped run id already names
the ids the store holds.

## The schemas, written down

`SKILL.md` now documents all three tables, because *what columns does `vqapr.fill` have* was a
question the surface could not answer and the journeys resolved by reading package internals:

- **`vqapr.account`** — the book over time.
- **`vqapr.fill`** — `instrument`, `kind`, `requested_quantity`, `dealt_quantity`, `price`,
  `commission`, `tax`, `cash_delta`, `reason`, `account_version`. The table cost questions are
  asked of: commission and tax are per fill and per side, so a category's true cost is a **sum over
  this table**, not a rate read off a venue.
- **`vqapr.weight`** — the intended allocation per evaluation, before execution.

Plus the five envelope fields every row of every table carries: `run_id`, `producer_id`, `stage`,
`event_time`, `sequence`. A table cannot declare one of these as a column of its own —
`TableSpec.__post_init__` refuses it.

The first draft of those lists got two columns the wrong way round, and the boundary gate's cleaner
lane caught it by comparing them against `DEFAULT_TABLES` and `FLOW_ENVELOPE_FIELDS` rather than
against the run output I had transcribed from. `event_time` is an envelope field on **every** table
and I had it as a per-table column of two of them; `observed_at` is a declared column of
`vqapr.account` **alone** and I had it as an envelope field on all three. Both errors pointed the
same way — toward selecting a column that is not there — and `vqapr.fill` is the table the skill
itself says cost questions are asked of, so it would have been the first casualty.

The distinction is load-bearing rather than pedantic: `RunRecordSpec.availability_field` exists
because the two clocks differ, and its docstring records a factor correlation moving from 0.93 to
0.02 when one was mislabelled as the other.

The skill also states the split `docs/issues/archive/013` records: a fill's `kind` is what the **roster**
said, while what it was **charged** as follows the venue's own terms, and nothing compares the two.
A reader summing cost by category needs to know that before they trust the sum.

## Validation

```
uv run pytest tests/ -q      # 1316 passed, 14 deselected
```

`tests/cli/test_commands.py::test_show_run_reads_back_the_tables_a_run_recorded` runs a real run
and then reads back every table it recorded, asserting for each that the readback's `rows_total`
**equals the record's own count for that table** — if the two disagree, one of them is lying about
the same run. It also pins `vqapr.fill`'s cost columns, checks that `--limit 1` reports
`returned: 1` with `rows_total > 1`, and that a mistyped table name refuses with the real table
list rather than reaching `stage: "unhandled"`.

`KINDS` is unchanged: this is a flag on an existing verb, not a new one.
