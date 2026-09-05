# Stop redoing what a frozen run already knows

## Why this exists

`kwam-enhanced-index` research replication was too slow to iterate on.
`docs/diagnostics/archive/2026-08-19-vqapr-performance.md` profiled the `run()` hot path and found the
common shape behind the two largest cheap wins: **a frozen run recomputes, on every callback,
facts that cannot change for the entire run.**

Two of those are fixed here. Both are pure recomputation removal. Neither changes what the run
observes, decides, or produces.

## What changed

### 1. Universe membership is a set lookup, not a tuple scan

`SimulationFlow._validate_intent_authority` checked every intent target against
`FrozenRun.instruments`, a `tuple[str, ...]`. That is a linear scan per target, so validating one
intent was `O(targets x universe)`.

`FrozenRun.__post_init__` already built a `set` to prove instrument uniqueness, then threw it
away. It is now kept as `instrument_set: frozenset[str]` and the membership test uses it.

Measured on this machine, 3,000 targets against a 3,000-name universe:

```
universe membership via tuple      28.918 ms
universe membership via frozenset   0.111 ms   -> 260x
```

The review estimated 170x. It was measuring the best case: identical string objects let CPython's
identity fast path short-circuit each comparison. Strategy-produced instrument ids are distinct
objects from the frozen run's, so the real penalty is worse than the review's estimate.

`instrument_set` is `field(init=False, repr=False, compare=False)`. It is derived state, not
declared state: it must not widen the constructor, and it must not participate in equality, where
it would be redundant with `instruments`. `FrozenRun`'s identity digest lists its contributing
fields explicitly, so a derived field cannot perturb run identity.

### 2. A source's byte digest is computed once per run, not once per query

`DuckDbObservationStore.query()` called `_physical_digest(source.path)` on every observation
query, re-reading and SHA256-hashing every byte of the source parquet each time. There was no
cache anywhere in the package.

The digest is now memoized on the store instance. `public.run()` builds exactly one
`DuckDbObservationStore` per run, and a run's sources are frozen for its whole duration, so
instance lifetime is exactly the correct cache scope.

**This strengthens an existing invariant rather than relaxing one.**
`SimulationFlow._actual_source_refs` already raises
`"one callback observed multiple byte digests for one source"`. Recomputing the digest per query
was one way to detect a violation; computing it once per run makes the violation unrepresentable.

Measured on the real `public.run()` spine (`showcases/show_005_enhanced_index`, two replicates):

| | before | after |
|---|---|---|
| digest calls | 504 | 8 |
| bytes re-hashed | 967,974 | 14,770 |
| digest wall time | 0.187 s | 0.003 s |

Re-hashed bytes equal query count times full source size, which is why this scales with warehouse
size rather than run length. At the review's reference scenario (500 MB source, ~8 queries per
session, 2,500 sessions) this path alone accounted for roughly 86 minutes of pure hashing.

`_physical_digest` now uses `hashlib.file_digest()` instead of a hand-rolled 1 MB read loop. The
two were proved to produce identical output over a multi-file source before the swap.

### 3. One physical connection per run, not one per query

Every function in `scan.py` opened a fresh `duckdb.connect()` and closed it in `finally`. A
connection is not just setup cost: duckdb caches parquet footers and row-group statistics for a
connection's lifetime, so closing after each query discarded that metadata and forced the next
query to re-expand the glob and re-parse footers.

`ScanSession` now holds one connection per source path for the lifetime of a run. **Connection
ownership stays inside `scan.py`**, which the module docstring declares to be the only place that
opens the physical layer; leaking a duckdb handle into `store.py` or `flow` would break that
boundary. Callers hold an opaque session and never see a connection.

`observation_rows`, `candidate_instants` and `exact_snapshot_rows` take `session: ScanSession |
None = None`. With `None` they open and close exactly as before, so every existing caller and test
is unaffected. `public.run()` creates one session and closes it in a `finally`, so a failed run
releases its handles.

Two details in the old `_open` had to survive: the path-existence check that produces a typed
`source.scan.path_missing` failure, and `SET preserve_insertion_order=false`. The existence check
was split into `_require_path` and is called on **every** session lookup, not only on connection
creation. Binding it to connection creation would have silently skipped it on the reuse path, and
the typed failure would have degraded into a raw duckdb exception.

Measured on `showcases/show_005_enhanced_index`:

| | before | after |
|---|---|---|
| duckdb connects | 714 | 210 |
| showcase wall time | 14.5 s | 7.78 s |

The remaining 210 come from `candidate_instants` and `exact_snapshot_rows`, reached through
`FillConvention` and `exact_execution_snapshot`. Those are value objects with no run-lifetime
state to hang a session on. Threading a session into them is deliberately left to the execution
instant cache work, which removes most of those calls outright rather than making each one
cheaper.

## Trade-offs

- `FrozenRun` carries one extra derived field. For a 3,000-name universe that is a few hundred KB
  of interned string references, held once per run, against a per-callback quadratic scan.
- The digest cache assumes source bytes do not change mid-run. That was already assumed: mutating
  a source mid-run would have tripped the multi-digest guard as a hard failure. The cache makes
  the assumption explicit and load-bearing instead of incidental.
- The cache is per store instance, not global. A process running two runs re-hashes per run. That
  is deliberate: a global cache would outlive the frozen-run scope that justifies it.
- A run now holds one open duckdb connection per source for its whole duration instead of opening
  and closing per query. That is the point, but it does mean a long run keeps file handles open.
  `public.run()` closes the session in `finally`, so this does not survive a failed run.
- `ScanSession` keys connections by source path. Two `SourceSpec` values pointing at the same path
  with different `hive_partitioned` settings would share a connection. That is safe because the
  hive flag is applied per query in `_relation`, not as connection state.

## What was deliberately not done

The review notes a cleaner final form for the digest: compute it at preflight/freeze time and
carry it on `FrozenRun`, so `run()` never hashes at all. That is a `FrozenRun` schema change and
the review explicitly says not to mix it with this one. It stays a separate task.

## Validation

```
uv run pytest -q                                    515 passed
uv run pytest tests/data/ tests/exchange/ tests/boundaries/ -q   80 passed
uv run python .agent/tmp/g4_check.py                G-4 PASS: 64 fields identical to baseline
uv run python .agent/tmp/perf_run_io.py             digest calls 8 / connects 210 / 7.78 s
uv run python .agent/tmp/perf_run_io.py --no-cache  digest calls 504 / bytes re-hashed 967,974
```

The binding check is result invariance, not speed. `showcases/show_005_enhanced_index` runs the
full spine twice into separate projects and compares artifact digests. Before and after these
changes it reports byte-identical output:

```
alpha_allocation.parquet      sha256:1446a91285c0d4d74e43c2a459cfe174833716958f99109709548b4b78b16de9
alpha_allocation.lineage.json sha256:5fc2576ddc45e7dbb95c7b2bc9792d10fd847c5c558ee340c25dcb593094e748
final NAV                     1168064370.53000000
committed cash                516418870.53000000
dealt fills                   62
```

A performance change to a backtest engine that alters one share, one weight, or one digest is not
a performance change. It is a defect. That snapshot, captured on a clean tree before any edit, is
the acceptance condition for every item in this series.
