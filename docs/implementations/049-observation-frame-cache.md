# Integrity-preserving observation frame cache

## Intent

Repeated observation queries in one flow reread the same registered CSV/Parquet columns and renormalized identical timestamps. The optimization must not weaken the frozen physical fingerprint or point-in-time contract, so source existence and SHA-256 remain mandatory on every query.

## Observable outcome

`ObservationStore` now keeps a private instance-local normalized frame for each `(registration_identity, resolved source path, physical fingerprint, field)` key. A cache hit skips only source read and timestamp normalization. Each query copies the cached pre-cutoff frame and independently applies as-of, session-date/timezone, point-observation, stable sort, and index reset behavior.

## Responsibilities and flow

The query validates aware input time, resolves the source, checks existence, and computes the registered SHA-256 before consulting the cache. A miss projects only required columns, normalizes availability and observation timestamps, applies any confirmed delay, and stores the unfiltered canonical frame. The field belongs to the key because its projected value column differs; registration identity prevents timezone and availability contracts over the same physical file from sharing frames.

## Alternatives and trade-offs

An mtime/size fast path was rejected because same-size, same-mtime content drift must still fail. A global cache and public invalidation API were rejected because they would create cross-project lifetime and ownership. The cache retains one normalized frame per queried field for the lifetime of one `ObservationStore`; large sources and many fields can therefore increase memory use, while separately created flows do not share cache entries.

## Validation

- `.venv/Scripts/python.exe -m pytest tests/test_observation_store_cache.py tests/test_data_registration.py tests/test_session_timezone.py tests/test_pit_research.py -q -p no:cacheprovider --basetemp .agent/test-runs/c5-focused-20260807-a` -> 28 passed in 3.22s.
- The focused counter test proves two warm queries perform two SHA-256 calls, one CSV read, and two timestamp normalizations. Mutating the first returned frame does not alter the cached result.
- Warm-cache deletion and same-size/same-mtime content drift both raise `DataSnapshotError`; registrations with different timezone contracts and fields produce isolated frames.
- Full-suite observation profile -> 243 passed in 323.32s. Compared with the pre-change 231-test profile, pandas reads fell from 322 to 254 and timestamp normalizations from 392 to 252 even though the final suite added twelve tests and query calls rose from 206 to 215. Store SHA-256 ran 214 times: once for every query whose source still existed; the deliberate deletion regression stopped at the required existence check.
- `.venv/Scripts/python.exe -m ruff check src/qlibx/data/store.py tests/test_observation_store_cache.py` -> passed.
- `git diff --check` -> passed before final documentation updates; completion validation reruns it.

## Remaining limitations

This is not a partitioned columnar store and does not reduce cold-read cost. SHA-256 remains a full-file operation by design, so immutable-source verification can dominate warm queries for large files. Cache lifetime is intentionally bounded to the owning `ObservationStore`, and there is no public cache-clear surface.