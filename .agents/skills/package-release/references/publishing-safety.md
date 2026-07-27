# Publishing safety

Before any upload, show:

- package name and version
- target index and publish URL
- exact artifact filenames and hashes
- source commit
- validation summary
- whether the operation is TestPyPI, PyPI, or a private index

Obtain explicit approval for that exact upload. Approval for TestPyPI does not authorize PyPI, and
approval for one version does not authorize another.

Prefer Trusted Publishing from an approved CI provider over a long-lived API token. If a token is
required, read it from a secure environment or credential store and never echo or commit it.

After upload, verify index metadata and install the published version in a fresh environment. Do not
delete, overwrite, or attempt to reuse a published version number as an automated recovery step.
