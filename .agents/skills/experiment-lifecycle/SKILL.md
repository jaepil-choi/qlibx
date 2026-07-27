---
name: experiment-lifecycle
description: Create, run, conclude, promote, and archive isolated experiments without polluting production tests.
---

# Experiment Lifecycle

Follow `experiments/AGENTS.md`.

- Allocate the next `exp_NNN_short_name/` directory; never reuse an ID.
- Keep the hypothesis, command, evidence, decision, freshness, and relationships in
  `experiment.yaml`.
- Store generated artifacts only in that experiment's `outputs/`.
- Do not add experiment-only helpers, fixtures, or tests under `src/` or `tests/`.
- Use `draft`, `running`, `concluded`, `promoted`, `rejected`, or `archived` status.
- Never silently overwrite conclusions. Link superseding experiments explicitly.
- Promotion is a separate production implementation task with its own validation and record.
