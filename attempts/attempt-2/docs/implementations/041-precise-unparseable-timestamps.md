# 041 — Precise unparseable timestamp failures

## Intent

Dataset registration previously coerced invalid timestamp text to `NaT` and then reported the resulting naive dtype as `TIMESTAMP_TIMEZONE_UNDECLARED`. That diagnosis was contradictory when zero rows parsed and led users through an unnecessary second failure. Registration must distinguish non-null parse failures, null availability, and parseable values whose timezone meaning is undeclared.

## Observable outcome

- Any non-null availability or observation-time value coerced to `NaT` fails as `TIMESTAMP_VALUES_UNPARSEABLE` before timezone validation.
- Failure evidence names the field, invalid count, up to three offending samples, stage, and requirement identity.
- Null availability retains `AVAILABLE_AT_INVALID`.
- Parseable naive timestamps still use `TIMESTAMP_TIMEZONE_UNDECLARED`.
- Failed validation never publishes registry state.

## Responsibilities and flow

`normalize_timestamps` classifies non-null parse failures from the original-value mask and returns all-null series for field-specific validation. `DatasetRegistry` maps the new failure to either `dataset.available_at` or `dataset.observation_time`, validates null availability before the unused-timezone check, and keeps timezone localization failures on the existing stage. The bundled recovery reference now gives a direct correction for the new public error code.

## Alternatives and trade-offs

Reusing `AVAILABLE_AT_INVALID` was rejected because the same normalizer also validates observation time and the code would misidentify that requirement. Treating all `NaT` values as unparseable was rejected because real null availability already has a distinct contract. `format="mixed"` avoids pandas inference warnings and supports heterogeneous explicit timestamp representations, while the subsequent dtype and timezone checks continue to reject mixed or ambiguous instant semantics.

## Validation

- `uv run ruff check src/qlibx/data/timestamps.py src/qlibx/data/registry.py tests/test_data_registration.py`
  - `All checks passed!`
- `uv run pytest tests/test_data_registration.py tests/test_session_timezone.py -q --basetemp .tmp/pytest-strategy-remediation-m3b-elevated`
  - `18 passed in 1.49s`

## Completion validation

- `uv run pytest tests -q --basetemp .tmp/pytest-strategy-remediation-full-20260807`
  - `220 passed in 453.97s`
- `uv run ruff check .` and `git diff --check`
  - passed; only pre-existing inaccessible ignored scratch-directory warnings and Git line-ending notices were emitted
- `uv build`
  - built `qlibx-0.1.0-py3-none-any.whl` and `qlibx-0.1.0.tar.gz`; archive inspection includes the changed production modules and bundled recovery guidance
- Fresh Python 3.12 wheel environment
  - installed the built wheel, ran the strategy-extension sample, loaded a deferred-annotation nested Pydantic extension, rejected post-registration source drift before execution, and filtered the mixed catalog by artifact type

## Remaining limitations

Timestamp parsing remains pandas-based and accepts the formats supported by the declared pandas range. This change improves classification; it does not infer a timezone or repair invalid source values.