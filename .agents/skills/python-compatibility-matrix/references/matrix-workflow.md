# Compatibility matrix workflow

For each supported Python minor version, collect evidence in this order:

1. **Metadata**: inspect the package and direct dependencies' `Requires-Python`.
2. **Resolution**: verify the lock or resolution covers the declared range.
3. **Install**: install into a fresh environment for the exact interpreter.
4. **Import**: import the package and required runtime dependencies.
5. **Smoke**: exercise a minimal public behavior without production data or external side effects.
6. **Tests**: run the repository-declared validation for that interpreter.
7. **Build**: create wheel and sdist using the declared build command.
8. **Artifact install**: install the built wheel into another fresh environment and repeat import and
   smoke checks.

Use exact interpreter requests, for example `uv run --python 3.13 ...` and
`uv run --python 3.14 ...`. Installing a missing interpreter or dependency may require network
approval in a restricted environment.

Do not mutate the lock while performing a frozen reproduction check. Distinguish `--locked` from
`--frozen`, and state which was used. If resolution falls back to building an sdist, invoke the
`corporate-windows` native-build reference on Windows.
