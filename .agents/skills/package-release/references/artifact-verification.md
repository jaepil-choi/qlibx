# Artifact verification

Verify artifacts, not only the source checkout:

1. Build wheel and sdist from the intended clean commit.
2. List artifact filenames, sizes, and SHA-256 hashes.
3. Inspect wheel and sdist contents for required package files and accidental data, credentials,
   caches, tests, experiments, showcases, or local configuration.
4. Validate package metadata, version, Python requirement, dependencies, entry points, license, and
   readme rendering.
5. Install the wheel into a fresh environment without editable or local-source overrides.
6. Repeat import and minimal public smoke checks.
7. Build a wheel from the produced sdist when practical and compare its behavior.
8. Keep verified artifacts immutable between approval and publication.

Generated release artifacts belong in the declared output directory and must not be confused with
experiment or showcase outputs.
