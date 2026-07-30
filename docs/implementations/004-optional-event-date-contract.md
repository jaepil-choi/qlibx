# Optional event-date contract

## Why

The logical-dataset schema and generated agent guidance described event time and availability as
two independent fields. That wording incorrectly made a separate `event_date` look mandatory even
though qlibx registration requires only `available_at`, `ticker`, and user-confirmed opaque
information.

## Outcome

`available_at` is now the only required time axis. It controls point-in-time visibility and is the
default field for range filtering; the standard matrix example uses it as the explicitly declared
index. A separate event or observation field is accepted only when a user chooses to preserve it as
opaque information and explicitly selects it in logical-dataset YAML.

## Responsibilities and flow

- Registration continues to create only the required `available_at` and `ticker` axes plus
  confirmed opaque information.
- Logical datasets default `availability_field` to `available_at`.
- When `time_field` is omitted, it resolves to the selected `availability_field`.
- Generated examples use `available_at` directly and do not invent `event_date`.
- Execution-profile introspection reports `event_time_field` as `null` when no separate time field
  was configured, while retaining `time_field` for the actual range-filter axis.

## Alternatives and trade-offs

Removing `time_field` entirely would prevent users from analyzing explicitly retained observation
or event dates. Keeping it optional preserves that use case without making it part of registration.
The `event_time_field` compatibility key remains in execution-profile output, but now accurately
distinguishes a separate optional field from the default availability axis.

## Validation

- `uv run pytest -q tests/test_data_flow.py tests/test_documentation.py tests/test_cli.py
  tests/test_execution_profile.py`: 19 passed. This covers an `available_at`-only registered
  Parquet and matrix, machine-readable schema output, generated agent skill/example, and the
  existing daily configuration with an explicit optional `event_date`.
- `uv run pytest -q`: 77 passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: 88 files already formatted.

The first restricted-token test attempt could not open the pre-existing shared uv cache. The same
command passed with a fresh task-specific cache under `C:\tmp`; no repository file or dependency
definition was changed to work around that environment permission issue.

## Remaining limitations

qlibx does not infer, synthesize, or validate the financial meaning of optional information fields.
Users remain responsible for confirming whether a source field should be retained and how it should
be used in logical SQL.
