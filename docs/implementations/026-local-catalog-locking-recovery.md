# 026 Local catalog locking and recovery

## Intent

Close `GAP-CATALOG-001` for the default single-host local backend. The previous backend validated
payloads and committed DuckDB envelope/lineage rows atomically, but it did not coordinate separate
writer processes or provide a durable, queryable account of publication attempts interrupted
between payload creation and index commit.

## Observable outcome

- Two processes publishing the same logical identity and content complete with the same artifact.
- Two processes publishing different content under one logical identity produce one complete
  artifact and one `ARTIFACT_IDENTITY_CONFLICT`.
- Process termination after staging or payload promotion never exposes reusable success. Explicit
  recovery removes the uncommitted files and a frozen-candidate retry completes deterministically.
- Process termination after catalog commit preserves the complete artifact; replay is idempotent.
- Lock timeout and unsupported catalog/event schema return typed failures without catalog mutation.

## Implementation

- `LocalArtifactBackend` serializes writers with a path-keyed in-process lock and an OS-backed
  cross-process lock file. Acquisition has a bounded timeout and does not add a service dependency.
- Catalog schema v1 adds `catalog_metadata` and append-only `publication_events`. The exact legacy
  `artifacts`/`artifact_edges` schema is adopted once; partial or unknown schemas fail explicitly.
- Publication records `STAGED`, fsyncs a staged payload, records `PAYLOAD_STAGED`, atomically moves
  it to its content-addressed path, records `PAYLOAD_PROMOTED`, then commits envelope, lineage, and
  `CATALOG_COMMITTED` in one DuckDB transaction.
- `audit_publications` returns typed versioned events. `recover_publications` removes only paths
  validated to remain under the artifact root and never promotes an uncommitted candidate.
- `tests/scenarios/catalog_recovery.yaml` owns the gap scenarios independently of prose documents.
  Tests use real spawned processes and deliberate process termination rather than a mocked catalog.

## Alternatives and trade-offs

Quack, DuckLake, PostgreSQL, SQLite migration, a catalog daemon, and a third-party locking package
were rejected for this local slice. They add deployment or dependency responsibilities not required
by the current product. The standard-library lock is explicitly single-host; multi-host and network
filesystem semantics remain unsupported until a backend proves the same contract.

Publication events retain backend-local absolute paths for audit and recovery. Portable artifact
identity and envelopes do not depend on those paths. Payload files are fsynced before promotion,
but power-loss durability of directory metadata remains operating-system/filesystem dependent; the
acceptance fixtures characterize process crash, not storage-device failure.

## Validation

- `uv run pytest tests/test_catalog_recovery.py tests/test_evidence.py -q` -> 15 passed.
- `uv run pytest -q` -> 103 passed in 111.62s.
- PRD/Architecture/scenario traceability suite -> 16 passed.
- Ruff, import smoke, Git diff check, and `uv build` -> passed.
- Built wheel contains the local backend and evidence contracts exactly once and contains no
  intraday runtime entry.

## Remaining work

`GAP-RECOVERY-001` still spans Account, Strategy Memory, feedback cursor, checkpoint, and artifact
publication. It should use this catalog boundary but is not implied complete by local publication
recovery.
