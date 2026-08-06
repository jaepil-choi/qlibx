# 031 Safe onboarding lifecycle

## Intent

Close `GAP-ONBOARD-001` without expanding into execution gating. The earlier onboarding path could
install and overwrite current bundled files, but it could not express removal, retire files that
disappeared from a newer bundle, validate the resulting state, or preserve instruction-file bytes
outside the managed section as an explicit contract.

## Observable outcome

An installed user can preview and apply either a `PRESENT` or `ABSENT` desired state for Codex,
Claude Code, or an explicit custom skill root. Existing callers remain `PRESENT` by default. The
result reports exact create/update/remove/unchanged/conflict actions, typed state validation, and a
`validation_argv` command that reruns the same operation as a non-mutating preview.

Update removes obsolete generated files only when the prior manifest fingerprint still matches and
preserves files that were never listed in that manifest. Remove deletes only fingerprint-confirmed
generated files and the qlibx-managed HTML-comment block. `AGENTS.md` and `CLAUDE.md` remain in place,
even if onboarding originally created them. Modified generated content, malformed markers, and
unsafe manifest paths stop the target before planned mutation.

## Responsibilities and flow

- `OnboardingDesiredState` owns the public `PRESENT`/`ABSENT` request, while the existing `apply`
  flag continues to distinguish preview from mutation.
- The target planner reads bundled resources, a prior manifest, current generated files, and the
  optional instruction file once to build a complete-state diff.
- Manifest schema v2 records generated-file hashes and managed-instruction metadata. The reader
  accepts schema v1 so an older install can be updated or removed without migration tooling.
- Manifest paths are treated as untrusted data. Only non-empty POSIX relative paths below the
  selected skill root are accepted; traversal, absolute, drive-qualified, and backslash paths fail.
- Instruction editing operates on bytes and replaces or removes only the single marker-delimited
  qlibx span. Bytes outside the span and the existing newline convention are preserved.
- Apply uses same-directory temporary files and replacement for writes, compares planned bytes
  before mutation, and writes or removes the manifest last as the durable ownership marker.
- Post-apply validation independently observes the entrypoint, manifest, managed block, and file
  fingerprints. Each target is planned and applied independently.

## Alternatives and trade-offs

A `--force` option was rejected because it would turn a fingerprint conflict into implicit ownership
of user edits. A separate `--check` mode was also rejected: preview already performs a read-only
state comparison, and `validation_argv` makes that operation reusable after apply.

Deleting an instruction file that becomes empty was rejected. Ownership is limited to the marked
block, not to the containing markdown file, so removal may intentionally leave a zero-byte file.

Tracking only the new bundle was rejected because it cannot identify obsolete generated files.
The complete-state plan uses the union of current bundle paths and prior manifest paths. Conversely,
scanning and deleting everything under the skill root was rejected because untracked extensions are
user-owned.

The implementation provides per-file atomic replacement and a manifest-last recovery marker, not a
multi-file filesystem transaction. A process interruption can leave an incomplete target; the next
preview rereads actual bytes and either completes the safe plan or exposes a fingerprint conflict.

## Validation

- Focused onboarding and CLI lifecycle tests:
  `uv run --cache-dir .uv-cache pytest tests/test_onboarding.py tests/test_cli.py --basetemp <unique C:\tmp path>`
  -> 15 passed in 0.86s.
- Lifecycle plus canonical-document traceability:
  `uv run --cache-dir .uv-cache pytest tests/test_onboarding.py tests/test_cli.py tests/test_document_traceability.py --basetemp <unique C:\tmp path>`
  -> 16 passed in 0.97s.
- Full suite:
  `uv run --cache-dir .uv-cache pytest -q --basetemp <unique C:\tmp path> -p no:cacheprovider`
  -> 142 passed in 120.42s.
- `uv run --cache-dir .uv-cache ruff check .` -> passed.
- Ruff format check over the six changed Python/test files -> all six already formatted. An additional
  repository-wide format check found 47 pre-existing unformatted files outside this task; they were
  not reformatted because that would expand the change scope.
- Public import:
  `uv run --cache-dir .uv-cache python -c "import qlibx; from qlibx import OnboardingDesiredState"`
  -> imported the checkout package and observed `OnboardingDesiredState.ABSENT.value == "absent"`.
- `git diff --check` -> passed with only Git's informational LF-to-CRLF warnings.
- `uv build --cache-dir .uv-cache` -> built `dist\qlibx-0.1.0.tar.gz` and
  `dist\qlibx-0.1.0-py3-none-any.whl`.
- Wheel inspection -> 103 entries, including `qlibx/onboarding.py`, the package root, bundled
  `SKILL.md`, `agents/openai.yaml`, and `references/error-recovery.md`.
- Installed-wheel smoke from isolated `C:\tmp` targets imported qlibx from the installed wheel,
  initialized a fresh project, applied Codex `PRESENT`, applied `ABSENT`, preserved `AGENTS.md`,
  removed the generated entrypoint, and returned the expected preview argv for both states.

## Remaining limitations

- There is no force-overwrite mode for modified generated content; recovery requires the user to
  reconcile or remove the conflicting edit explicitly.
- Onboarding does not compose constraint, execution, Account, or OMS behavior.
- Cross-process multi-file transactions are not provided; recovery is manifest- and
  fingerprint-driven.