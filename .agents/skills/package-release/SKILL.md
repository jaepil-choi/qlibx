---
name: package-release
description: Prepare, build, inspect, and publish a Python package release with artifact-first verification and explicit publication approval. Use for release candidates, version bumps, wheel or sdist builds, TestPyPI or PyPI publication, private-index publication, Trusted Publishing, release checklists, or diagnosing why an installed artifact differs from the source checkout.
---

# Release a Python Package

Publishing is an external state change and always requires explicit authorization for the exact
repository, version, index, and artifact set. Preparing and validating artifacts does not authorize
upload.

1. Confirm a clean, reviewed tree and the intended version and target index.
2. Confirm canonical requirements, release notes, compatibility range, and current showcases.
3. Run the full declared validation and `python-compatibility-matrix`.
4. Run every release-only gate the project manifest declares, and commit whatever it writes. These
   record facts about the artifact that only a release can establish, so a gate skipped here is
   not discovered until the release after it.
5. Build wheel and sdist from the repository using the declared command and with development-only
   source overrides disabled.
6. Follow `references/artifact-verification.md`.
7. Review the final artifact list and hashes.
8. Follow `references/publishing-safety.md`; obtain explicit approval immediately before upload.
9. After upload, verify package metadata and installation from the target index without modifying
   the source tree.
10. Record the released commit, version, artifact hashes, validation, index, and remaining caveats.

Never publish from an uncommitted tree, reuse unverified artifacts, expose an API token, silently
replace an existing version, or treat a successful upload as proof that installation works.
