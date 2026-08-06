# 033 Require declared timezone meaning for source timestamps

## Intent

Dataset registration and query converted naive timestamps with `utc=True`, silently treating local
wall times as UTC. The registry also published append-only JSON with `os.rename`, which rejects an
existing destination on Windows but replaces it on POSIX. Both behaviors made correctness depend on
an undeclared convention or development platform.

## Observable outcome

Naive availability and observation timestamps are accepted only with a user-confirmed IANA
`source_timezone`. They are localized before UTC conversion, and the evidence reports the timezone
that was actually used. Offset-qualified sources reject an unused declaration. Mixed, ambiguous or
nonexistent local times fail before publication with typed diagnostics.

Dataset registration is create-if-absent on Windows and POSIX. A concurrent or pre-existing identity
is never overwritten, and a filesystem without atomic hard links returns
`REGISTRY_PUBLICATION_FAILED` with `commit_status=NONE`.

## Responsibilities and flow

- `DatasetRegistration` validates the timezone declaration; `RegisteredDataset` persists it with a
  backward-compatible `None` default.
- `normalize_timestamps` owns strict naive/aware classification, localization and UTC conversion.
  Registry and observation-store reads use the same rule.
- `DatasetRegistry` validates both timestamp axes, preserves the existing availability NaT check,
  applies confirmed delay after instant conversion, and records `localized_source_timezone`.
- Publication writes a same-directory temporary JSON and atomically links it to a previously absent
  destination. A losing writer re-reads the winner; other filesystem errors become typed failures.
- Acceptance fixtures whose physical parquet timestamps are naive UTC now say so explicitly. Bundled
  and public-surface fixtures with offsets remain unchanged.

The raw schema fingerprint is unchanged because it is still computed from physical dtypes before
normalization. Registration identities intentionally change because the new field is part of the
frozen registration payload.

## Alternatives and trade-offs

Rejecting every naive source was rejected because known warehouse fixtures have a confirmed UTC
storage convention. Defaulting `source_timezone` to UTC was rejected because it would preserve the
silent economic assumption. Excluding the field from identity was rejected because two different
time meanings must not share an identity.

An `open(destination, "x")` fallback was rejected: it prevents overwrite but exposes a partially
written registry JSON to readers. Filesystems without hard-link support fail explicitly instead of
weakening append-only publication.

## Validation

```
.venv/Scripts/python.exe -m pytest tests/test_data_registration.py tests/test_cli.py -q -p no:cacheprovider --basetemp=.agent/runs/pytest-c2-targeted-019fd96d
-> 15 passed in 16.12s

.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp=.agent/runs/pytest-c2-full-019fd96d
-> 147 passed in 320.78s

.venv/Scripts/python.exe -m ruff check .
-> All checks passed!

git diff --check
-> clean
```

## Remaining limitations

- Re-registering a pre-upgrade dataset under the same dataset ID reports
  `REGISTRATION_IDENTITY_CONFLICT`; it is not silently migrated.
- Querying a legacy registration whose physical timestamps are naive reports `DataSnapshotError`
  until the source timezone is explicitly registered.
- Resume across the changed registry fingerprint requires the existing explicit branch workflow.
- Atomic publication requires same-filesystem hard-link support; remote filesystems without it are
  reported as unsupported rather than receiving a weaker fallback.