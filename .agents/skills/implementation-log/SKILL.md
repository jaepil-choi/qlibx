---
name: implementation-log
description: Record the intent and engineering reasoning for an authorized production source change.
---

# Implementation Log

Use this skill only when approved work changes production source behavior, a production script,
runtime configuration or schema, or package contracts.

Create a record under the `implementation_log_root` declared in `.agent/project.yaml`. Use a stable,
human-readable filename that does not depend on a commit that does not yet exist.

The record must explain:

- Why the change was needed.
- What user or system outcome it serves.
- How responsibilities and flow were changed.
- Alternatives and trade-offs.
- Exact validation commands and results.
- Remaining limitations and follow-up work.

Include the implementation record in the same commit as the source change. Keep the commit subject
concise; do not turn it into a duplicate design document.

Do not create a record for harness-only, documentation-only, experiment-only, or showcase-only work.
