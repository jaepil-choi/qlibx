# Deterministic query-snapshot layout and explicit migration

## Intent

Registration normalized source data into content-addressed Parquet but retained source row order.
Consequently, Parquet row-group statistics and predicate pruning depended on a vendor's dump order,
and two logically identical sources could produce different query-snapshot fingerprints. Existing
schema-v2 registrations also had no physical-layout identity, so `reindex_datasets()` treated every
valid v2 snapshot as current and could not migrate an old layout.

The change makes the physical query layout deterministic while preserving point-in-time filtering,
logical-key ordering, registration identity, immutable source/snapshot verification, and the
existing explicit reindex surface.

## Benchmark decision

An ignored task-scoped harness generated the same 3,000-instrument x 1,500-session (4.5M-row) panel
in two Parquet files with identical 122,880-row group settings. One was ordered time-major and the
other instrument-major. Every result frame was asserted equal. Each workload was warmed once and
then measured five times inside one frozen scope on Windows 11, Python 3.12.13, DuckDB 1.5.5,
pandas 2.3.3, and pyarrow 23.0.1.

| Workload | Time-major median | Instrument-major median | Selected-layout effect |
|---|---:|---:|---:|
| midpoint, broad session | 8.4 ms | 34.9 ms | 76% lower |
| midpoint, broad latest | 78.6 ms | 76.1 ms | 3% higher |
| midpoint, broad rows-20 | 183.2 ms | 155.5 ms | 18% higher |
| final, broad session | 9.7 ms | 33.3 ms | 71% lower |
| final, broad latest | 170.6 ms | 168.4 ms | 1% higher |
| final, broad rows-20 | 355.9 ms | 319.2 ms | 11% higher |
| final, narrow latest (10 instruments) | 42.3 ms | 25.6 ms | 66% higher |
| final, narrow rows-20 (10 instruments) | 46.8 ms | 27.6 ms | 69% higher |

No layout dominates every access shape. Time-major was selected because the public `session()`
surface is necessarily a full cross-section and daily execution repeatedly uses it for price and
volume. Narrow filters exist for latest/history, where the measured trade-off remains explicit.
This is a product-workload choice, not a claim that time-major is universally fastest.

## Responsibilities and flow

New query snapshots use layout version 2 and stable ascending order:

1. normalized `available_at`;
2. normalized `observation_time`, with missing values last;
3. canonical string `instrument`, with missing values last;
4. every registered logical-key projection in declared order, with missing values last.

The registered logical key is unique, so the final sequence provides a complete tie break. A stable
sort also makes logically identical sources with different row order converge to the same snapshot
bytes and fingerprint.

`DatasetQuerySnapshot.layout_version` defaults to 1 when absent so old JSON remains parseable. The
outer `registration_schema_version` remains 2 because registration shape and semantic bindings did
not change. Querying layout v1 fails with `DATASET_QUERY_SNAPSHOT_LAYOUT_REQUIRED` and directs the
caller to `project.reindex_datasets()`. Reindex still verifies the registered source and any existing
snapshot before mutation, rebuilds only old-layout registrations, retains the original registration
identity, writes the content-addressed snapshot first, and atomically replaces the registry pointer.
A second reindex is unchanged and reports `changed=False`.

## Alternatives and trade-offs

- Instrument-major was rejected as the global layout despite improving small-instrument histories
  and bounded aggregation. It made the mandatory broad session read 3.4x to 4.2x slower.
- `registration_schema_version=3` was rejected because this transition describes physical Parquet
  ordering, not a new registration or semantic-binding contract.
- Silently accepting layout v1 was rejected because it would leave performance dependent on source
  order and make migration state invisible.
- Rewriting the existing snapshot in place was rejected. Content-addressed files remain immutable;
  only the registration pointer changes after a successful build.

## Validation

- `uv run python .agent/tmp/snapshot_layout_benchmark.py setup .agent/tmp/snapshot-layout-benchmark`
  -> generated both 4.5M-row layouts with 37 row groups each.
- `uv run python .agent/tmp/snapshot_layout_benchmark.py run .agent/tmp/snapshot-layout-benchmark`
  -> completed the matrix above; all frames were equal across layouts.
- `uv run python -m pytest tests/test_data_registration.py tests/test_exact_lookback.py -q -p no:cacheprovider`
  -> 24 passed in 3.51s.
- `uv run python -m pytest tests/test_data_registration.py tests/test_exact_lookback.py tests/test_observation_store_cache.py tests/test_session_timezone.py -q -p no:cacheprovider`
  -> 33 passed in 4.01s.
- `uv run python -m pytest tests -q -p no:cacheprovider` -> 300 passed in 145.68s.
- `uv run ruff check .` -> all checks passed.
- `uv run python -c "import qlibx"` -> passed.
- `uv build` -> built `dist/qlibx-0.1.0.tar.gz` and
  `dist/qlibx-0.1.0-py3-none-any.whl`.
- `git diff --check` -> passed.

## Remaining limitations

Parquet ordering is one global compromise and is not an index. Instrument-major narrow reads remain
faster in the measured case, while latest and rows-lookback still scan every row group admitted by
their predicates. The benchmark is local performance evidence rather than a cross-platform latency
guarantee. No automatic background migration is introduced; old-layout registrations deliberately
require the explicit reindex command.
