# Showcase Rules

These rules apply only under `showcases/`.

- Every showcase lives in `show_NNN_short_name/`; allocate monotonically increasing IDs and never
  reuse or renumber an ID.
- Each directory contains `showcase.yaml`, a reader-facing `README.md`, a reproducible entry point,
  and a local `outputs/` directory.
- Generated output belongs in `showcases/show_NNN_short_name/outputs/`, never in a shared global
  showcase output directory. Outputs are not committed.
- A showcase must cite its source experiment or released behavior and record
  `verified_against`, `last_verified_at`, the exact reproduction command, and environment assumptions.
- Valid status values are `draft`, `current`, `stale`, `superseded`, and `archived`.
- A showcase is `current` only after its documented command succeeds against the recorded package
  state.
- Do not add or modify anything under `tests/` solely for a showcase.
- Keep showcase-only presentation and orchestration outside production source.
- When behavior or dependencies change, re-verify or mark the showcase stale. Never leave outdated
  evidence presented as current.
