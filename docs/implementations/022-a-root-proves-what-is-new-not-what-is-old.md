# A root proves what is new, not what is old

## Why this exists

`docs/diagnostics/archive/2026-08-19-vqapr-performance.md` identified two costs that grow quadratically
with run length. Both live in `AcceptedRunState.__post_init__`, and both have the same shape:

> Every new root re-does, from scratch, work that every previous root already did.

A root is created roughly four times per session (callback publish, account commit, marked,
feedback). At callback `k` each root re-validated all `k` accumulated model states and re-wrapped
every recorder row written so far. Per-session cost therefore grew linearly with how far the run
had already progressed, making total cost quadratic in run length.

This is why a one-year backtest felt fine while a ten-year backtest was not ten times slower but
a hundred times slower.

## What changed

### 1. Recorder rows accumulate as chunks

`__post_init__` rebuilt the entire recorder history on every root:

```python
recorder_rows = {
    name: tuple(MappingProxyType(dict(row)) for row in rows)   # every row, every root
    for name, rows in self.recorder_rows.items()
}
```

Rows are now stored per table as a tuple of per-callback chunks (`_recorder_chunks`). Appending a
callback's rows appends one chunk, which costs the size of that chunk and not the size of history.
Each row is wrapped read-only exactly once, where its chunk is created.

`recorder_rows` survives unchanged as a property that flattens chunks on read. Every existing
consumer keeps working: `publish_run_record` reads it once after the run, and tests and showcases
index it as `recorder_rows["diagnostics"][0]["sequence"]`.

The re-wrap was not protecting anything that chunking loses. Rows reaching a root have already
passed `normalize_rows` twice, once in `InvocationRecorder.append_batch` and again in
`staged_rows()`, and `normalize_rows` returns detached dicts. The invariant that mattered was that
a caller cannot mutate a published row, and that is preserved by wrapping once at chunk creation.

Note that `normalize_rows` returns plain `dict`, not a read-only mapping. Dropping the wrap
entirely would have silently made published rows mutable, so the wrap moved rather than
disappeared.

### 2. A root verifies only refs no previous root has proved

`__post_init__` re-derived every accumulated `ModelStateRef` by re-serialising its memory to JSON
and re-hashing it with SHA256:

```python
for ref, memory in self._model_states.items():        # the whole accumulated history
    if prepare_model_state(memory, payload).ref != ref:
        raise ValueError(...)
```

A `ModelStateRef` can only be minted by `prepare_model_state`. Re-deriving one for a ref that an
earlier root already proved re-proves nothing.

`AcceptedRunState` now carries a private `_verified: frozenset[ModelStateRef]` and checks only
`set(self._model_states) - self._verified`. `prepare_callback` passes `root._verified |
{candidate.ref}`, because `candidate` came straight from `prepare_model_state` and is proved by
construction. The four root-to-root copies that carry states forward unchanged pass `_verified`
through.

**`_verified` defaults to `frozenset()`.** A root constructed from outside this module is verified
in full, exactly as before. The fast path requires an explicit claim from the previous root, so
the safe behaviour is the default rather than something a caller must remember to ask for.

`normalize_memory` is likewise skipped for already-verified refs, since their memory was
normalised by the root that proved them.

## Proof that the quadratic term is gone

The acceptance fixture is far too small to show this: a quadratic term in run length is invisible
across a handful of callbacks. `.agent/tmp/perf_axis_b.py` drives `prepare_callback` directly for
increasing callback counts, and `.agent/tmp/perf_axis_b_control.py` restores the pre-fix
`__post_init__` by monkeypatch and runs the identical harness.

| callbacks | before, per callback | after, per callback | speedup |
|---|---|---|---|
| 100 | 8.17 ms | 1.36 ms | 6x |
| 200 | 15.46 ms | 1.57 ms | 10x |
| 400 | 30.55 ms | 1.46 ms | 21x |
| 800 | 77.14 ms | 1.54 ms | 50x |

Before, per-callback cost roughly doubles as N doubles (x1.89, x1.98, x2.53), and the second half
of a run costs up to 4x the first half. That is the quadratic signature. After, per-callback cost
is flat near 1.5 ms and the two halves cost the same.

Total wall time for 800 callbacks: **61.71 s before, 1.23 s after.**

The speedup is not a constant. It grows with run length, which is the entire point: it is largest
exactly where the problem was worst.

## Trade-offs

- A root holds a `frozenset` of refs proportional to accumulated model states. That set replaces
  re-hashing every one of those states on every root.
- `recorder_rows` is now O(total rows) per read instead of free, having previously been O(total
  rows) per *write* with roughly four writes per session. The only in-run reader is
  `publish_run_record`, after the run ends.
- `_recorder_chunks` is a private field, so anything constructing `AcceptedRunState` directly and
  passing `recorder_rows=` would now be passing an unknown keyword. Only `run_state.py` constructs
  it; the single test that builds one directly never passed that field.

## What was deliberately not done

`_model_states`, `_payloads` and `fill_history` still grow without bound and are never pruned,
while only `current_model_state_ref` is ever read. At 2,500 callbacks with a 50 KB payload that is
roughly 125 MB resident for no observed purpose. Whether canon requires the full history to stay
resident is an open question for the user, recorded in the review's section 8. This change makes
that history cheap to carry; it does not decide whether it should be carried.

## Validation

```
uv run pytest -q                                515 passed
uv run pytest tests/flow/ tests/acceptance/ -q  157 passed
uv run python .agent/tmp/g4_check.py            G-4 PASS: 64 fields identical to baseline
uv run python .agent/tmp/perf_axis_b.py         per-callback flat 1.36 -> 1.54 ms across 100..800
uv run python .agent/tmp/perf_axis_b_control.py per-callback 8.17 -> 77.14 ms across 100..800
```

The tamper guard was checked directly rather than assumed, since this change touches it: a root
built externally with a payload that does not match its ref, and one with memory that does not
match its ref, are both still rejected with `ModelStateRef must identify its exact memory and
payload`. An honest root still constructs.

Result invariance holds. `showcases/show_005_enhanced_index` reports byte-identical artifacts,
NAV, committed cash, replayed positions and fill counts against the snapshot taken before any of
this work began.
