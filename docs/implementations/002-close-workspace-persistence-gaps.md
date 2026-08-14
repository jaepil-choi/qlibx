# Close workspace persistence gaps

## Why this change exists

The first workspace persistence slice made each YAML replacement atomic, but it serialized the
calling instance's in-memory snapshot without rereading durable state. A directly constructed or
stale instance could therefore erase declarations that were already on disk. An equal
re-registration also returned `False` after the workspace file had been deleted, falsely claiming
that the declaration remained durable.

The stored dataset entry contained only a `source_id`. It discarded the corresponding
`SourceSpec.path` and `hive_partitioned` declaration, so a later command could not reconstruct the
physical half of registration. Invalid dataset IDs also escaped lookup as raw `ValueError` values
instead of the structured failure surface used by agents.

## Outcome

Workspace YAML now preserves registration's two architectural layers:

- `sources` stores each physical `SourceSpec` as `path` and `hive_partitioned` under `source_id`;
- `datasets` stores each semantic `DatasetRegistration` and references its source by ID.

`Workspace.register_dataset(registration, source)` requires the two source IDs to match and stores
the pair together. A reopened workspace can return both `dataset()` and `source()` values without
the caller reconstructing physical configuration by hand.

Direct construction is rejected; callers use `Workspace.create()` or `Workspace.open()`. Every
registration rereads the YAML before deciding whether the operation is new, idempotent, or in
conflict. A stale sequential instance merges with that durable state, while a deleted workspace
fails as `workspace.open.missing` instead of returning an incorrect no-op result.

## Responsibility and flow

```text
validated DatasetRegistration + SourceSpec
  -> Workspace.register_dataset(...)
  -> reread current .vqapr/workspace.yaml
  -> validate source ID match and source/dataset declaration conflicts
  -> merge with current durable declarations
  -> temporary file + fsync + os.replace
  -> refresh the calling instance only after a successful replacement
```

The workspace still does not open parquet or repeat schema/key validation. `data/scan.py` and
`data/datasets.py` retain those responsibilities. Paths are persisted exactly as declared; this
change does not add cwd discovery or absolute-path normalization.

Lookup input errors and absent declarations now use stable structured identities:

- `workspace.dataset.lookup.invalid`
- `workspace.dataset.lookup.missing`
- `workspace.source.lookup.invalid`
- `workspace.source.lookup.missing`

Source/dataset registration failures remain non-mutating and distinguish ID mismatch from a
conflicting physical declaration:

- `workspace.dataset.register.source_mismatch`
- `workspace.dataset.register.source_conflict`

## Alternatives and trade-offs

- **Keep only the source ID** was rejected because later commands cannot recover the path or Hive
  reading mode, and manually recreating them would make the workspace incomplete.
- **Embed a full source under every dataset** was rejected because the architecture separates
  physical source configuration from semantic dataset registration and allows datasets to share a
  source.
- **Trust the instance snapshot for idempotence** was rejected because it can disagree with the
  durable file after another command or deletion.
- **Recreate a deleted workspace implicitly** was rejected because deletion may be intentional and
  an opened instance is not authority to resurrect project configuration silently.
- **Normalize `key_fields` order** was not included. The canonical documents do not declare an
  ordered tuple to be order-insensitive, and logical keys also participate in deterministic row
  ordering beyond uniqueness checks.
- **Add a writer lock or compare-and-swap** was deferred. Reread-and-merge prevents deterministic
  sequential stale-instance loss but does not coordinate truly overlapping writers.

## Evidence and validation

Regression-first evidence against `d4d97a6` produced five failures for direct-construction bypass,
stale overwrite, deleted-file idempotence, missing source persistence, and raw invalid-ID lookup.

After implementation:

```text
uv run pytest -q tests/test_workspace.py
-> 17 passed in 0.22s

uv run python scripts/evidence_workspace.py
-> real-data validation ok=True
-> separate writer/reader PIDs
-> source_round_trip_equal=True, hive_partitioned=True
-> datasets_after_stale_write=['one', 'three', 'two']
-> deleted workspace and invalid/missing lookups returned structured mutation=false errors
```

Completion validation:

```text
uv run pytest -q
-> 63 passed in 1.20s

uv run pytest -q -m "not real_data"
-> 59 passed, 4 deselected in 0.70s

uv run ruff check src tests scripts
-> All checks passed

uv run ruff format --check src tests scripts
-> 146 files already formatted

uv run python -c "from vqapr.workspace import Workspace; print(Workspace.__name__)"
-> Workspace

uv build
-> built dist/vqapr-0.1.0.tar.gz and dist/vqapr-0.1.0-py3-none-any.whl
-> wheel contains vqapr/workspace.py

git diff --check
-> passed; Git emitted only the checkout's LF-to-CRLF warnings for the three changed Python files
```

## Remaining limitations and follow-up

- Truly overlapping writers are not locked and can still race between reread and replacement.
- Replace semantics and an audit history remain intentionally unsupported.
- Whether `.vqapr/` should be shared or ignored depends on future project guidance and path policy.
- `key_fields` declaration order remains identity-sensitive until the canonical contract says
  otherwise.
