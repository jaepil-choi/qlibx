# Bounded catalog recovery scans

## Intent

Publication called recovery before every write, and recovery deserialized the entire append-only event log. The cost grew with all historical attempts even though recovery only acts on attempts without a terminal event. The optimization must retain the canonical rule that malformed or unknown event schemas block both audit and publication without mutation.

## Observable outcome

Recovery deserializes only events belonging to unterminated attempts. Completed catalogs return zero recovery rows. A lightweight DuckDB JSON guard still scans event schema versions before publication, so malformed JSON, missing versions, and unsupported versions remain `CATALOG_SCHEMA_UNSUPPORTED` failures.

## Responsibilities and flow

`LocalArtifactBackend._read_events()` remains the complete audit path. `_read_unterminated_events()` first validates every stored `event_schema_version`, then filters out attempts containing `CATALOG_COMMITTED` or `RECOVERED_ABANDONED` using enum-derived parameters. Both readers delegate Pydantic construction and error translation to `_deserialize_events()`.

## Alternatives and trade-offs

Filtering attempts without the schema guard was rejected because it would hide corrupt terminal event JSON from publication and violate `CATALOG-EVENT-SCHEMA-001`. Re-deserializing every terminal event was rejected because it preserves the original scaling cost. The schema guard is still a vectorized linear SQL scan, measured at 6.546ms for 20,000 rows versus 15.945ms for returning the full log; it preserves integrity at a smaller but non-constant cost. Event phase count, durability boundaries, event-order allocation, and catalog schema remain unchanged.

## Validation

Baseline on HEAD `ce15634`, same machine:

```text
published   ms/publish
      100        344.1
      200        331.4
      300        345.0
      400        362.5
      500        428.4
      600        373.6
      700        384.6
      800        443.3
last/first = 1.29x
```

After this change:

```text
published   ms/publish
      100        346.9
      200        342.2
      300        383.3
      400        372.1
      500        371.8
      600        422.6
      700        391.9
      800        403.3
last/first = 1.16x
```

Commands and results:

- `.venv/Scripts/python.exe -m pytest tests/test_catalog_recovery.py -q --basetemp .agent/test-runs/catalog-c1-focused -p no:cacheprovider` -> 12 passed in 12.42s.
- `.venv/Scripts/python.exe experiments/exp_001_catalog_performance/bench_publish.py 800` -> final/first bucket 1.16x; final bucket 403.3ms versus 443.3ms baseline.
- `.venv/Scripts/python.exe -m ruff check src/qlibx/evidence/local.py tests/test_catalog_recovery.py experiments/exp_001_catalog_performance` -> passed.
- `.venv/Scripts/python.exe -m pytest tests -q --basetemp .agent/test-runs/catalog-c1-full -p no:cacheprovider` -> 233 passed in 428.02s.

## Remaining limitations

The all-row schema-version guard is linear in event count and does not make publication asymptotically constant. It deliberately preserves corruption detection. A future schema migration could index event schema versions, but no migration is justified by the current measurements.