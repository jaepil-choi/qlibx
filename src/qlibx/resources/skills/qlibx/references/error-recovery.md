# Error recovery

Use the exact public error fields. Candidate actions are guidance, not package-owned defaults.

| Error family | Meaning | Safe next actions |
|---|---|---|
| SOURCE_NOT_FOUND or SOURCE_READ_FAILED | The declared physical source is unavailable or unreadable | Correct the explicit source or format |
| BOUND_FIELD_MISSING | A confirmed binding names a field absent from the source | Rebind an existing field or choose another source |
| LOGICAL_KEY_NULL or LOGICAL_KEY_DUPLICATE | The declared logical identity is invalid | Correct rows or add the real event/sequence key |
| AVAILABLE_AT_INVALID | The confirmed availability input cannot be parsed | Choose a release timestamp, supported delay rule, or enriched source |
| TIMESTAMP_TIMEZONE_UNDECLARED | A naive timestamp has no declared timezone meaning | Confirm its IANA source timezone or provide offset-qualified timestamps |
| TIMESTAMP_TIMEZONE_UNUSED | A timezone was declared although every parsed timestamp already carries an offset | Remove the unused source_timezone declaration |
| TIMESTAMP_LOCALIZATION_FAILED | Local timestamps are mixed, ambiguous, or nonexistent | Provide offset-qualified timestamps that identify exact instants |
| REGISTRY_PUBLICATION_FAILED | The filesystem cannot publish the immutable registration atomically | Use a local filesystem that supports atomic hard-link creation |
| REQUIREMENT_NOT_RESOLVED | The selected operation needs an unregistered semantic capability | Add a binding/dataset, derive it, select another profile, or validate an extension |
| ARTIFACT_IDENTITY_CONFLICT | The same logical identity already has different immutable content | Retain it or choose a new logical identity |
| ARTIFACT_PAYLOAD_INVALID | Serialized content violates its documented contract | Fix the producer payload before import |
| CONSTRAINT_COMPUTE_FAILED, MONITORING_COMPUTE_FAILED, or ANALYSIS_COMPUTE_FAILED | An unexpected defect occurred after immutable inputs were materialized | Preserve the error and frozen inputs, report the diagnostic, and retry only after the implementation or input contract changes |

Do not retry until every retry_precondition is either satisfied or explicitly rejected by the
user. A retry is a new invocation linked to the prior error; it never deletes the failure record.

An unexpected compute failure is deterministic for the same frozen input and implementation.
Repeating that invocation is diagnostic reproduction, not recovery. Keep the failure artifact,
report its stage, exception type, and immutable input identities, then use a new linked invocation
only after a code fix or an explicit input-contract change.
