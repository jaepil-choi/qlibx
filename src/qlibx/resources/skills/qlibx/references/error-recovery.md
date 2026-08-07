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
| ARTIFACT_IDENTITY_CONFLICT | The same logical identity already has different immutable content | Retain it or choose a new logical identity |
| ARTIFACT_PAYLOAD_INVALID | Serialized content violates its documented contract | Fix the producer payload before import |
| STRATEGY_EXTENSION_MODULE_INVALID or STRATEGY_EXTENSION_CONTRACT_INVALID | The local file is outside the extension root, cannot import, lacks fixed symbols, returns a singleton, or declares an invalid Strategy contract | Keep one trusted `.py` file under the configured extension root, fix `STRATEGY_SPEC` / zero-argument `create_strategy()`, and validate again |
| STRATEGY_EXTENSION_ARTIFACT_MODEL_INVALID | A declared project-local payload model is not module-local, has an unstable schema, or collides with a built-in contract | Rename the project contract, define one local `QlibxModel`, or use the existing built-in payload contract |
| STRATEGY_EXTENSION_NONDETERMINISTIC or STRATEGY_EXTENSION_VALIDATION_FAILED | Fresh instances differ or the frozen fixture cannot supply a view input/output contract | Remove hidden random/global/wall-clock state, provide exact fixture artifacts, and validate a new frozen request |
| STRATEGY_EXTENSION_REGISTRATION_INVALID or STRATEGY_EXTENSION_LOAD_FAILED | The selected exact registration cannot be loaded or reconstructed | Select a successful registration artifact ID and restore its declared local dependencies/path |
| STRATEGY_EXTENSION_SOURCE_DRIFT or STRATEGY_EXTENSION_CONTRACT_DRIFT | Current source or declaration no longer matches the selected registration | Validate the changed module and explicitly select the new registration ID; never fall back to latest compatible |
| CONSTRAINT_COMPUTE_FAILED, MONITORING_COMPUTE_FAILED, or ANALYSIS_COMPUTE_FAILED | An unexpected defect occurred after immutable inputs were materialized | Preserve the error and frozen inputs, report the diagnostic, and retry only after the implementation or input contract changes |

Do not retry until every retry_precondition is either satisfied or explicitly rejected by the
user. A retry is a new invocation linked to the prior error; it never deletes the failure record.

An unexpected compute failure is deterministic for the same frozen input and implementation.
Repeating that invocation is diagnostic reproduction, not recovery. Keep the failure artifact,
report its stage, exception type, and immutable input identities, then use a new linked invocation
only after a code fix or an explicit input-contract change.
