# 078 — A damaged row is an answer

The red-team lane's last finding of the run: append one line of invalid JSON to a run's recorded
table and `vqapr show run <id> --table <name>` crashed with a raw `JSONDecodeError` as
`stage: "unhandled"`.

`read_table` was a bare generator calling `json.loads` on every non-blank line, and `show.py`
consumed it in a plain loop. An **empty** table file was already handled — zero rows, `ok: true` —
so the gap was specifically a non-blank line that does not parse.

## Reported, never skipped

The tempting fix is to skip the bad line and carry on. That would be worse than the crash.

`show run` reports each table's row count from the record, and `--table` reports `rows_total` from
the file. Skipping a damaged row makes those two numbers disagree with no reason given — a reader
comparing them finds a short table that looks complete and has nothing to go on. The whole point of
T9 is that the readback and the record describe one run.

So it refuses, and locates the row:

```
cli.input.value_invalid
requirement: every line of 'vqapr.fill' must be one JSON row
observed   : .../tables/vqapr.fill.jsonl line 5 is not one JSON row: Expecting value...
             The recorder wrote this file, so a line that does not parse means it was edited or
             truncated; restore it, or re-run under a new run id
```

**An empty file stays legal**, and blank lines stay skipped. A run may record a table and write
nothing to it, and that is an outcome rather than damage. The two cases look alike from the
reader's side, so they are pinned by two separate tests rather than one.

## Where the refusal is built

`flow/run_records.py` raises a `ValueError` with a precise message; `cli/show.py` catches it and
renders the structured refusal. That follows the module's existing convention — `read_record`
raises `FileNotFoundError` naming the known run ids — and the boundary discipline the architect
lane endorsed for `_class_name` in record `073`: bare exceptions in the layer that detects, a
structured `code`/`requirement`/`observed`/`fix` at the CLI edge.

Putting a `VqaprError` in `run_records.py` would have given the lowest-level record module a
dependency on the error vocabulary that no other function in it uses.

## Validation

```
uv run pytest tests/ -q
```

- `test_show_run_reads_back_the_tables_a_run_recorded` gained the damaged-row case: `stage` is not
  `"unhandled"` and the refusal names the line.
- `test_an_empty_recorded_table_reads_back_as_empty_not_as_broken` pins the legal case separately,
  including blank lines, so a future narrowing of one cannot quietly swallow the other.

This is the **fifth distinct** `stage: "unhandled"` defect the completion gates found across the
three slices, counting a guard that turned out to be one layer short as the same defect it failed
to close — which is the rule record `075` already uses when it calls itself "three crashes" and
then describes two more that were narrower fixes of the same three. By the other consistent rule,
counting every gate finding separately, it is the eighth. The first draft of this sentence said
"sixth", which is neither, and the cleaner lane caught it: six requires counting Slice A's
layer-deeper finding as its own crash while not counting Slice B's two, and nothing supports that
asymmetry.

The number is the least interesting part. The pattern held to the end, and holds under either rule:
every one arrived through input a real project produces, and every one was in code that had just
been written or just been touched.
