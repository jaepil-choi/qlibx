---
name: showcase-lifecycle
description: Maintain reproducible, current showcases as evidence of proven package behavior.
---

# Showcase Lifecycle

Follow `showcases/AGENTS.md`.

- Allocate the next `show_NNN_short_name/` directory; never reuse an ID.
- A showcase must cite the experiment or released behavior it demonstrates.
- Store generated artifacts only in that showcase's `outputs/`.
- Record the exact reproduction command, environment assumptions, `last_verified_at`, and
  `verified_against`.
- Do not add showcase-only helpers, fixtures, or tests under `src/` or `tests/`.
- Mark outdated evidence `stale`, `superseded`, or `archived`; do not present it as current.
- Refresh a showcase only after its documented reproduction succeeds.
