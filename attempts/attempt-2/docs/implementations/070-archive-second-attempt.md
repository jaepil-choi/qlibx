# 070 — Archive the second qlibx attempt

## Why

The repository is moving from the `qlibx` library identity to a new `vqapr` design. Keeping the
second qlibx production tree at the repository root would mix two product contracts and make later
renaming ambiguous. The second implementation must remain inspectable as evidence without being
presented as the active package.

## Outcome

The complete tracked second-attempt implementation, tests, experiments, showcases, qlibx-era
documentation, and package metadata are preserved under `attempts/attempt-2/`. The newer vqapr PRD
and architecture remain at root. Obsolete ignored `qlibx-research/` runtime state is removed.

## Responsibility and flow changes

- Active root package source and qlibx tests are retired from the root and become frozen reference
  material.
- Attempt-specific validation and demonstration material moves with the implementation it proves.
- Canonical product-document routing changes from the moved qlibx-era path to
  `docs/vqapr-prd.md`.
- Package/module/CLI renaming is deliberately deferred to the next task and commit.

## Alternatives and trade-offs

Leaving tests or showcases at root was rejected because they directly import the retired qlibx
source and would falsely look current. Deleting current source was rejected because Git history and
file times show it is the second implementation, not an attempt-1 duplicate. Copying all ignored
outputs was rejected as a Git concern; ignored generated state is not part of the commit.

The archive commit is intentionally transitional: the root `pyproject.toml` still names qlibx while
root source is absent. Import/build validation therefore belongs to the subsequent vqapr rename,
not this archival commit.

## Validation

Before relocation:

- `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp <isolated>` under scoped
  Windows permission: `283 passed, 2 failed in 323.18s`.
- Both failures were pre-existing local data-audit drift in `tests/test_data_source_audit.py`: the
  current sector parquet hash differs and has 1,143,059 rows versus the recorded 187,615.
- Sandboxed runs failed with `WinError 5` while pytest accessed its basetemp; the same suite ran
  under the narrow approved pytest boundary, separating environment failure from code results.

After relocation:

- Explicit index-scope assertion: `304` renames, `7` additions, and `2` modifications across `313`
  staged entries; every source and destination path matched the approved archive scope.
- Archive index inventory: `120` source files, `66` test files, `12` showcase files, `12`
  experiment files, and `95` qlibx-era documentation files; `311` tracked attempt-2 files total.
- Root inventory: only `docs/vqapr-prd.md` and `docs/vqapr-architecture.md` remain under `docs/`;
  root `src/`, `tests/`, `showcases/`, `experiments/`, and `qlibx-research/` are absent.
- Tracked Python compilation: `162` files compiled successfully with `py_compile`.
- YAML lifecycle check: `2` experiments remain `concluded`; all `3` moved showcases are explicitly
  `archived`.
- The archived `.gitignore`, `.python-version`, `README.md`, `pyproject.toml`, and `uv.lock` index
  blobs exactly match their pre-archive `HEAD` blobs.
- `git diff --cached --check`: passed; non-ignored untracked files: none.

## Remaining limitations and follow-up

- The root is not a valid installable package between this archive commit and the planned vqapr
  package rename/rebuild.
- Local data-audit drift remains intentionally unchanged and is preserved as baseline evidence.
- No commit is pushed by this task.
