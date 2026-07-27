---
name: dependency-change
description: Make controlled dependency and lockfile changes in a uv-managed Python package, including production, optional, development, build, or private-index dependencies. Use for uv add, remove, upgrade, downgrade, marker or index changes, pytest or Ruff setup, lockfile refreshes, dependency-conflict diagnosis, vulnerability remediation, or any request that can alter pyproject.toml, uv.toml, or uv.lock.
---

# Change Dependencies Safely

Read `.agent/project.yaml`, the current package metadata, lockfile, and repository approval policy.
Confirm the requested dependency role and supported Python range before mutating files.

1. Establish the exact package, allowed version range, dependency group, index provenance, and reason.
2. Capture the relevant pre-change tree and lock state.
3. Use the narrowest uv command. Do not broaden an upgrade to unrelated packages.
4. Inspect the metadata and lock diff using `references/lock-review.md`.
5. For a private index or proxy, follow `references/private-index.md` and the
   `corporate-windows` skill when applicable.
6. Verify resolution for the declared Python range. Invoke `python-compatibility-matrix` for support
   claims or version-sensitive dependencies.
7. Run install, import, narrow tests, lint, and build checks that apply.
8. Record why the dependency is needed, selected constraints, provenance, transitive impact, and
   validation in the implementation record when production behavior changes.

Do not store credentials in project files, use insecure index settings, remove bounds merely to make
resolution pass, or regenerate a lockfile without reviewing its transitive changes.
