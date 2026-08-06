# Error recovery

Use the exact public error fields. Candidate actions are guidance, not package-owned defaults.

| Error family | Meaning | Safe next actions |
|---|---|---|
| SOURCE_NOT_FOUND or SOURCE_READ_FAILED | The declared physical source is unavailable or unreadable | Correct the explicit source or format |
| BOUND_FIELD_MISSING | A confirmed binding names a field absent from the source | Rebind an existing field or choose another source |
| LOGICAL_KEY_NULL or LOGICAL_KEY_DUPLICATE | The declared logical identity is invalid | Correct rows or add the real event/sequence key |
| AVAILABLE_AT_INVALID | The confirmed availability input cannot be parsed | Choose a release timestamp, supported delay rule, or enriched source |
| REQUIREMENT_NOT_RESOLVED | The selected operation needs an unregistered semantic capability | Add a binding/dataset, derive it, select another profile, or validate an extension |
| ARTIFACT_IDENTITY_CONFLICT | The same logical identity already has different immutable content | Retain it or choose a new logical identity |
| ARTIFACT_PAYLOAD_INVALID | Serialized content violates its documented contract | Fix the producer payload before import |

Do not retry until every retry_precondition is either satisfied or explicitly rejected by the
user. A retry is a new invocation linked to the prior error; it never deletes the failure record.
