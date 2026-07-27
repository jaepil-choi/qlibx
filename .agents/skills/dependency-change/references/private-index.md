# Dependency provenance and credentials

- Define indexes without credentials in committed configuration.
- Supply secrets through approved environment variables, credential stores, or keyring providers.
- Keep the default safe index strategy unless repository policy explicitly changes it.
- Pin internal packages to an explicit named index when provenance must be enforced.
- Treat 401/403, certificate errors, proxy failures, and missing packages as distinct diagnoses.
- Never use an insecure host setting to make dependency resolution pass.
- Verify that no credential-bearing URL appears in `pyproject.toml`, `uv.toml`, `uv.lock`, logs, or
  implementation records.
