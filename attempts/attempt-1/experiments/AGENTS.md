# Experiment Rules

These rules apply only under `experiments/`.

- Every experiment lives in `exp_NNN_short_name/`; allocate monotonically increasing IDs and never
  reuse or renumber an ID.
- Each directory contains `experiment.yaml`, the independently runnable experiment entry point,
  concise notes when needed, and a local `outputs/` directory.
- Generated output belongs in `experiments/exp_NNN_short_name/outputs/`, never in a shared global
  experiment output directory. Outputs are not committed.
- `experiment.yaml` records `id`, `status`, `created_at`, `last_verified_at`, `hypothesis`,
  `command`, `decision`, `outputs`, `supersedes`, and `superseded_by`.
- Valid status values are `draft`, `running`, `concluded`, `promoted`, `rejected`, and `archived`.
- Record actual commands, evidence paths, conclusions, limitations, and follow-up.
- Do not add or modify anything under `tests/` solely for an experiment.
- Keep experiment-only code self-contained. Do not add helpers to production source for experiment
  convenience.
- Promotion into production is a separate explicitly requested task. Link the promoted
  implementation back to the experiment.
- Review stale experiments by `last_verified_at`, dependency or contract changes, and superseding
  evidence. Mark lifecycle state explicitly instead of silently deleting history.
