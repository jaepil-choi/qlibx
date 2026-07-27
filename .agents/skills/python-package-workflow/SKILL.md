---
name: python-package-workflow
description: Execute bounded, evidence-driven work in a reusable Python package repository.
---

# Python Package Workflow

1. Establish the task contract and inspect the relevant responsibility before editing.
2. Read commands and canonical documents from `.agent/project.yaml`.
3. Use an ExecPlan when `.agent/policy.yaml` requires one.
4. Work one milestone at a time and keep changes inside the requested scope.
5. Use the declared environment manager; do not create an unrequested environment.
6. Validate narrowly during iteration, then run the manifest-declared completion checks that apply.
7. Fail explicitly on missing schema, command, dependency, or contract. Do not hide failure behind
   an unapproved fallback.
8. Update durable plan and run state before compaction or handoff.
9. If production behavior changed, follow the `implementation-log` skill.
10. Do not stage, commit, push, or publish without authorization.
