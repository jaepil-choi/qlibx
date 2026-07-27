---
name: python-compatibility-matrix
description: Verify a Python package across its declared interpreter range with layered evidence for metadata, dependency resolution, installation, import, smoke behavior, tests, and built artifacts. Use when adding or changing Python support, validating Python 3.13 or 3.14, checking an upstream package whose metadata is more conservative than observed runtime behavior, changing dependencies, diagnosing version-specific failures, or preparing a release compatibility claim.
---

# Verify Python Compatibility

Read `.agent/project.yaml`, the package metadata, and the canonical requirements before choosing the
matrix. Do not infer support from one successful import or from uv's interpreter support.

Use an ExecPlan when the matrix includes multiple interpreters or artifact installation.

1. Record the declared Python range and exact interpreter patch versions.
2. Run the stages in `references/matrix-workflow.md`.
3. Classify every version using `references/evidence-schema.md`.
4. Preserve upstream metadata mismatches instead of silently rewriting or bypassing them.
5. Separate a resolver workaround from verified runtime compatibility.
6. Use fresh environments for installation and artifact checks; do not reuse a contaminated
   environment as release evidence.
7. Run the repository's declared validation commands. Do not add tests solely for experiments or
   showcases.
8. Record exact commands, exit codes, artifact paths, and limitations in the active plan or
   implementation record.

Never claim support for a version unless all acceptance-required stages pass. When upstream metadata
is conservative but runtime checks pass, report both facts and label the support risk explicitly.
