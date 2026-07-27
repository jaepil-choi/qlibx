# Lockfile review

Compare before and after:

- requested direct dependency and group
- version constraint and environment markers
- added, removed, upgraded, and downgraded transitive packages
- source and index provenance
- wheel versus source-distribution availability
- supported-Python coverage
- build dependencies and platform-specific packages

Use `uv tree` and the lock diff to explain unexpected movement. Do not accept unrelated upgrades
merely because resolution succeeds. For reproducible validation, state whether `uv lock --check`,
`uv run --locked`, or `uv run --frozen` was used.

When publishing a package, verify the build with project-specific uv sources disabled using the
repository-declared equivalent of `uv build --no-sources`.
