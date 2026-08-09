# Error recovery

Use the exact public error fields. Candidate actions are guidance, not package-owned defaults.

| Error family | Meaning | Safe next actions |
|---|---|---|
| SOURCE_NOT_FOUND or SOURCE_READ_FAILED | The declared physical source is unavailable or unreadable | Correct the explicit source or format |
| BOUND_FIELD_MISSING | A confirmed binding names a field absent from the source | Rebind an existing field or choose another source |
| LOGICAL_KEY_NULL or LOGICAL_KEY_DUPLICATE | The declared logical identity is invalid | Correct rows or add the real event/sequence key |
| AVAILABLE_AT_INVALID | The confirmed availability input is null or otherwise lacks a usable instant | Choose a release timestamp, supported delay rule, or enriched source |
| TIMESTAMP_VALUES_UNPARSEABLE | A non-null availability or observation-time value cannot be parsed | Correct the bounded offending values before declaring timezone semantics |
| TIMESTAMP_TIMEZONE_UNDECLARED | A naive timestamp has no declared timezone meaning | Confirm its IANA source timezone or provide offset-qualified timestamps |
| TIMESTAMP_TIMEZONE_UNUSED | A timezone was declared although every parsed timestamp already carries an offset | Remove the unused source_timezone declaration |
| TIMESTAMP_LOCALIZATION_FAILED | Local timestamps are mixed, ambiguous, or nonexistent | Provide offset-qualified timestamps that identify exact instants |
| REGISTRY_PUBLICATION_FAILED | The filesystem cannot publish the immutable registration atomically | Use a local filesystem that supports atomic hard-link creation |
| REQUIREMENT_NOT_RESOLVED | The selected operation needs an unregistered semantic capability | Add a binding/dataset, derive it, select another profile, or validate an extension |
| MATERIALIZATION_CONTRACT_INVALID or MATERIALIZATION_RESULT_INVALID | The selected operation or returned payload violates the public materialization contract | Fix the operation declaration/result schema; do not publish or coerce an incompatible payload |
| MATERIALIZATION_REQUIREMENTS_FAILED or MATERIALIZATION_RESOLUTION_ERROR_INVALID | Requirements cannot be declared or the selected prior failure is not a valid linked requirement-resolution error | Correct the declaration or select the exact prior materialization failure artifact, then use a new invocation |
| MATERIALIZATION_DATA_READ_FAILED | A declared PIT dataset could not be read after requirement resolution | Restore the immutable registered source and fingerprint; do not substitute another source silently |
| MATERIALIZATION_COMPUTE_FAILED | An unexpected producer defect occurred after immutable inputs were materialized | Preserve the failure and frozen inputs; retry only after a code or explicit input-contract change |
| FORWARD_LABEL_INPUT_EMPTY or FORWARD_LABEL_COVERAGE_MISMATCH | Required label roles have no common instrument/observation coverage | Correct the explicit datasets so start, end, and horizon rows have exact key coverage |
| FORWARD_LABEL_VALUE_INVALID or FORWARD_LABEL_HORIZON_INVALID | A label value is non-positive/non-finite or its horizon/availability ordering is invalid | Correct source values or declared horizon semantics; never invent a delay or drop offending rows silently |
| ARTIFACT_IDENTITY_CONFLICT | The same logical identity already has different immutable content | Retain it or choose a new logical identity |
| ARTIFACT_PAYLOAD_INVALID | Serialized content violates its documented contract | Fix the producer payload before import |
| CATALOG_SESSION_CONFLICT | Another thread or process owns the bounded exclusive catalog session | Wait until the active workflow finishes, then retry the whole operation; do not bypass the catalog lock |
| STRATEGY_EXTENSION_MODULE_INVALID or STRATEGY_EXTENSION_CONTRACT_INVALID | The local file is outside the extension root, cannot import, lacks fixed symbols, returns a singleton, or declares an invalid Strategy contract | Keep one trusted `.py` file under the configured extension root, fix `STRATEGY_SPEC` / zero-argument `create_strategy()`, and validate again |
| STRATEGY_EXTENSION_ARTIFACT_MODEL_INVALID | A declared project-local payload model is not module-local, has an unstable schema, or collides with a built-in contract | Rename the project contract, define one local `QlibxModel`, or use the existing built-in payload contract |
| STRATEGY_EXTENSION_NONDETERMINISTIC or STRATEGY_EXTENSION_VALIDATION_FAILED | Fresh instances differ or the frozen fixture cannot supply a view input/output contract | Remove hidden random/global/wall-clock state, provide exact fixture artifacts, and validate a new frozen request |
| STRATEGY_EXTENSION_REGISTRATION_INVALID or STRATEGY_EXTENSION_LOAD_FAILED | The selected exact registration cannot be loaded or reconstructed | Select a successful registration artifact ID and restore its declared local dependencies/path |
| STRATEGY_EXTENSION_SOURCE_DRIFT or STRATEGY_EXTENSION_CONTRACT_DRIFT | Current source or declaration no longer matches the selected registration | Validate the changed module and explicitly select the new registration ID; never fall back to latest compatible |
| CONSTRAINT_COMPUTE_FAILED, MONITORING_COMPUTE_FAILED, or ANALYSIS_COMPUTE_FAILED | An unexpected defect occurred after immutable inputs were materialized | Preserve the error and frozen inputs, report the diagnostic, and retry only after the implementation or input contract changes |

Do not retry until every retry_precondition is either satisfied or explicitly rejected by the
user. A retry is a new invocation linked to the prior error; it never deletes the failure record.

For unresolved `label.horizon_end`, report that exact requirement and offer only a confirmed binding,
a separately registered or derived dataset, or a different model. Do not guess a horizon from file
names, row order, observation frequency, or a conventional trading-day count.

An unexpected compute failure is deterministic for the same frozen input and implementation.
Repeating that invocation is diagnostic reproduction, not recovery. Keep the failure artifact,
report its stage, exception type, and immutable input identities, then use a new linked invocation
only after a code fix or an explicit input-contract change.
