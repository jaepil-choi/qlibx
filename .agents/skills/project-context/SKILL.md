---
name: project-context
description: Load project-specific context through the repository manifest without polluting reusable root instructions.
---

# Project Context

1. Read `.agent/project.yaml`.
2. Resolve only the canonical documents needed for the current task.
3. State which canonical documents were used.
4. Treat `references/` as historical or comparative material unless the manifest says otherwise.
5. If a required canonical path is missing, fail explicitly instead of substituting a similarly
   named reference file.
6. Keep project facts out of reusable skills and the root `AGENTS.md`; update the manifest when
   routing changes.
