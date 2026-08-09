# Latest recovery-point lookup

## Intent

Resume must locate one latest recovery point without loading every recovery artifact.

## Observable outcome

The local catalog exposes `latest_envelope(artifact_type, logical_identity_prefix)`, implemented with DuckDB `starts_with` and descending logical identity order. Run IDs containing SQL wildcard characters remain literal. Recovery identities retain eight-digit sequences and fail with `RECOVERY_SEQUENCE_EXHAUSTED` before overflow.

## Responsibilities and flow

The catalog performs the bounded lookup; daily resume validates the selected envelope and reads only the linked recovery chain needed for restoration.

## Alternatives and trade-offs

SQL `LIKE` was rejected because `%` and `_` would change run identity semantics. Full catalog scans were rejected because restart cost would grow with unrelated history.

## Validation

`uv run python -m pytest tests -q -p no:cacheprovider` passed 247 tests in 114.80s, including literal `%/_` prefixes, recovery, catalog, and crash-matrix regressions. `uv run ruff check .`, the ignored `import qlibx` smoke script, and `uv build` also passed.
