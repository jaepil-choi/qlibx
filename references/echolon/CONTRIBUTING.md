# Contributing to Echolon

Thanks for considering a contribution. This is a small, focused project — issues and pull requests are welcome.

## Reporting issues

Open an issue at <https://github.com/dolphinquant/echolon/issues>. Useful info to include:

- The output of `echolon doctor` (catches dependency mismatches early).
- The full structured `EchelonError` traceback if applicable — error codes (`[CODE-NNN]`) plus the parameterized `fix` string carry most of what we need to triage.
- A minimal reproduction: the strategy directory, the data layout, and the exact CLI command.

For LLM-driven workflows: paste the agent's transcript when possible — it's often clearer than a paraphrased description.

## Pull requests

1. Fork the repo and create a topic branch off `master`.
2. Run the test suite locally before opening the PR:
   ```bash
   pip install -e ".[dev]"
   pytest tests/ --ignore=tests/live
   ```
   The full suite must pass. `tests/live/` is intentionally skipped — it requires network/broker access.
3. If you change a public API, update the relevant skill (`echolon/native/skills/`) and any error code docs (`echolon/native/errors/codes/`) so the agent surface stays in sync with code.
4. Add a CHANGELOG entry under the next-release section. Mark breaking changes clearly.

## Code style

- Library code MUST NOT silently call `PathsConfig.from_env()` as a fallback. Every public entry point takes `paths: PathsConfig` as a required kwarg. The CLI command layer is the only legitimate place to construct paths from env / cwd defaults.
- New `EchelonError` codes need a corresponding markdown doc under `echolon/native/errors/codes/<CODE>.md` and an entry in the `ERROR_CATALOG` registry.
- New MCP tools belong in `echolon/mcp/` and should have a matching skill under `echolon/native/skills/echolon_api/<tool_name>/SKILL.md`.

## Scope

Currently end-to-end production scope is **SHFE daily futures** only. Crypto / CME / equities / live trading have architectural slots but no shipped implementation. If you want to drive one of those forward, open an issue first to align on approach before sending a large PR.

## License

By contributing you agree your contribution is licensed under Apache 2.0 (the project's license).
