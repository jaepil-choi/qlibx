# 047 — A long scan draws duckdb's progress bar into the same stdout the CLI writes its JSON envelope to, so a slow command's output does not parse

**Status: CLOSED 2026-09-02 by
[`129-three-debts-that-cost-nothing-to-pay.md`](../implementations/129-three-debts-that-cost-nothing-to-pay.md).**
Both duckdb connection factories in `src/vqapr/data/scan.py` now go through one `_configure`, which
sets `enable_progress_bar=false` alongside the `preserve_insertion_order=false` that was already
there.

**Two things measured while closing it are worth carrying forward, because a one-line patch would
have got both wrong.** `enable_progress_bar` is `LOCAL` scope, so (1) **a cursor does not inherit
its parent's value** — silencing the shared database would leave every `ScanSession` cursor
unconfigured — and (2) **the default is the host's decision, not a constant**: duckdb 1.5.5 turns
the bar *on* when `__main__` has no `__file__` (a REPL, a notebook, `python -c`, an embedding host)
and off when it does. That second fact is why the regression test turns the bar on before asserting
`_configure` turns it back; asserting only that a factory's connection is quiet would pass under
pytest against a `_configure` that did nothing.


**Status when filed:** open. Found 2026-08-31 in
`kwam-enhanced-index/vqapr-performance-testbed/`, against `vqapr-0.2.0a2` (built wheel). The
workaround it forces was already in the wild — see below — with no record of why.
**Touches:** `src/vqapr/data/scan.py:150` (`_open`) and `src/vqapr/data/scan.py:205`
(`ScanSession.connection`), the two places a duckdb connection is created.

## What happens

Both connection factories set `preserve_insertion_order=false` and nothing else. duckdb's progress
bar defaults to on, and it renders **to stdout even when stdout is a pipe**. Any command whose scan
runs long enough to trigger it therefore emits this:

```
  95% ▕██████████████████████████████████  ▏ (~2 seconds remaining)  {"ok": true, "registered": ...}
```

Carriage-returned progress frames, then the envelope, on one stream. `vqapr register` of a
37.8M-row source takes 5.5s and reliably crosses the threshold; so does any materialization or run
that opens a large source.

## It is already being worked around, by someone who did not know why

`vqapr-enhanced-index-3/pipeline.py` — the driver for a twelve-book factor build — reads every
command's result like this:

```python
completed = subprocess.run(["uv", "run", "vqapr", *arguments], capture_output=True, ...)
payload = (completed.stdout or completed.stderr).strip()
...
if '"ok": true' in payload:
```

A substring test against the raw stream, not `json.loads`. That is the shape a caller ends up with
when the envelope is not reliably alone on stdout, and it costs the caller everything the envelope
was built to give: a refusal's `code`, its `fix`, its `retry_precondition`, its `correlation_id`.
The driver's failure path prints the first 2,000 bytes and asks a human to read it.

The testbed hit the same thing and worked around it the same way — first by scanning backwards for a
line that parses, then by wrapping `duckdb.connect` to disable the bar. Two independent consumers,
same workaround, and neither found it documented.

## Why this is the package's to fix rather than the caller's

The envelope is the package's contract with an agent. `docs/` treats it as such: a six-field typed
refusal, a correlation id, a diagnostics path. An agent parsing that contract has no way to know
that a *slow* command speaks a different dialect than a fast one — and it is exactly the slow
commands whose failures are expensive to misread.

A caller can redirect stdout, or filter, or guess. None of those is discoverable, and all of them
are the caller repairing a stream the package chose to share.

## The fix

One statement beside the one already there, in both factories:

```python
con.execute("SET preserve_insertion_order=false")
con.execute("SET enable_progress_bar=false")
```

`ScanSession.connection` creates cursors on one database, so setting it on the database when it is
first opened covers every cursor taken from it.

## What to settle

Whether the bar should be *unavailable* or merely *off by default*. A human running `vqapr run`
interactively on a five-minute materialization is the one case where it earns its keep, and
[035](035-the-only-data-accessor-is-ninety-times-slower-than-the-file.md) plus
`VQAPR-ISSUES.md` A4 in the research environment both record the same complaint from the other
direction — that a long run gives no sign of life. If progress is worth showing, it belongs on
**stderr**, or behind an explicit flag, and the envelope stream stays clean either way. What cannot
stand is progress and contract sharing one pipe.
