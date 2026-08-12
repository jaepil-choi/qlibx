# Bounded observation top-N and frozen connection reuse

## Intent

`ObservationStore.latest()` and exact `RowsLookback` ranked every point-in-time-visible row with a
DuckDB window before discarding all but one or N rows per instrument. A representative 4.5M-row
panel therefore spent far more time ranking accumulated history than returning its bounded result.
Each query also opened and closed a separate in-memory DuckDB connection, including repeated reads
inside one already-frozen public invocation.

The change must improve those paths without introducing a guessed time lower bound, weakening PIT
filtering or physical fingerprint verification, changing logical-key tie breaking, or changing
the access evidence derived from the returned frame.

## Observable outcome

For the same 3,000-instrument x 1,500-session chronological Parquet snapshot, warm queries inside one
`frozen()` scope changed as follows on Windows 11, Python 3.12.13, DuckDB 1.5.5, pandas 2.3.3, and
pyarrow 23.0.1:

| Query | Before median | After median | Reduction |
|---|---:|---:|---:|
| one session | 26.9 ms | 7.7 ms | 71% |
| `latest()` | 1,366.2 ms | 160.0 ms | 88% |
| `RowsLookback(rows=20)` | 1,606.1 ms | 343.8 ms | 79% |

The benchmark used one warm-up per mode, seven timed repetitions, an `as_of` after the final row,
and source/snapshot verification memoized by the same frozen scope. It is local performance evidence,
not a cross-platform latency guarantee.

## Responsibilities and flow

The existing SQL predicate still establishes the complete PIT-visible relation, including optional
instrument, session, point, and calendar bounds. Only the per-instrument bounded selection changed:

1. Each visible row is packed into a private struct containing the result fields and generated
   aliases for every registered logical-order column.
2. `create_sort_key(..., 'DESC NULLS LAST')` encodes the exact former ordering for `available_at`,
   `observation_time`, and the logical-order columns.
3. DuckDB `arg_min(payload, sort_key)` selects latest; its three-argument top-N form selects exact
   rows lookback. The latter list is unnested and returned in the same ascending public order.
4. A DuckDB connection is created lazily on the first query in the outermost `frozen()` scope,
   reused by nested scopes and subsequent queries, and closed once in outer-scope cleanup. A query
   outside `frozen()` continues to own and close a standalone connection.

The query plan changes the 4.5M-row per-instrument selection from a full `WINDOW` row-number operator
to `HASH_GROUP_BY` with bounded `arg_min`. The Parquet scan remains present; this change reduces
ranking/selection work rather than claiming indexed lookup.

## Alternatives and trade-offs

- A fixed `available_at` prefilter was rejected because sparse or ragged instruments can have their
  Nth row before any globally guessed lower bound, silently changing exact results.
- A raw struct comparison was measured but rejected for production because the required null order
  would be implicit. `create_sort_key` makes every `DESC NULLS LAST` decision explicit.
- Eager connection creation at `frozen()` entry was rejected because public operations that never
  read observations would pay a new connection cost. Lazy acquisition preserves that path.
- A global connection, pool, or thread-safety claim was rejected. Connection lifetime remains local
  to one `ObservationStore` and one outer frozen invocation.
- Snapshot reordering/versioning is N-05 and remains outside this change. No registration or artifact
  schema changed.

## Validation

- `uv run python -m pytest tests/test_exact_lookback.py tests/test_observation_store_cache.py -q -p no:cacheprovider`
  -> 12 passed in 4.13s.
- `uv run python -m pytest tests/test_observation_store_cache.py tests/test_exact_lookback.py tests/test_data_registration.py tests/test_session_timezone.py -q -p no:cacheprovider`
  -> 30 passed in 2.86s.
- `uv run ruff check src/qlibx/data/store.py tests/test_exact_lookback.py tests/test_observation_store_cache.py`
  -> all checks passed.
- An ignored task-scoped 4.5M-row harness recorded the before/after medians in the table above and
  preserved the current/candidate query plans.
- `uv run --no-project --with duckdb==1.3.0 python .agent/tmp/duckdb_minimum_smoke.py`
  -> DuckDB 1.3.0 top-N sort-key smoke passed on Python 3.12.13.
- `uv run --no-project --python 3.11 --with duckdb==1.3.0 python .agent/tmp/duckdb_minimum_smoke.py`
  -> DuckDB 1.3.0 top-N sort-key smoke passed on Python 3.11.15.
- `uv run python -m pytest tests -q -p no:cacheprovider` -> 297 passed in 180.34s.
- `uv run ruff check .` -> all checks passed.
- `uv run python -c "import qlibx"` -> passed.
- `uv build` -> built `dist/qlibx-0.1.0.tar.gz` and `dist/qlibx-0.1.0-py3-none-any.whl`.
- `git diff --check` -> passed.

## Remaining limitations

The Parquet reader still scans all row groups admitted by its predicates, so cost can still grow with
history. The bounded aggregate removes full per-instrument ranking but is not an index. Physical
snapshot order and row-group pruning remain the separately gated N-05 decision. Connection reuse is
not a thread-safety contract, and standalone queries intentionally retain per-query connection
ownership.
