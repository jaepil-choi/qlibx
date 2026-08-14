# Register datasets through the public facade

## Why this change exists

Dataset declarations could be validated and persisted only by importing implementation modules
such as `vqapr.data.datasets`, `vqapr.data.sources`, and `vqapr.workspace`. That contradicted
`UC-FACADE-001`: an installed-package consumer must be able to complete registration without
opening package source or depending on internal import paths.

The composition boundary was also missing. A caller had to know that validation must finish before
workspace persistence. Getting that order wrong could store an invalid declaration or create
project state for a failed validation.

## Outcome

`vqapr.public` now exposes the minimal registration surface:

- `SourceSpec`
- `DatasetRegistration`
- `VqaprError`
- `register_dataset(project_root, registration, source)`

The operation returns `True` for a new durable declaration and `False` for an equal idempotent
retry. It does not introduce another result type. Failures retain the existing `VqaprError` and
`as_dict()` contract.

## Responsibility and flow

```text
public SourceSpec + DatasetRegistration
  -> data.datasets.validate()
  -> Diagnosis.raise_if_failed()
  -> Workspace.create(project_root)
  -> Workspace.register_dataset(registration, source)
  -> bool changed
```

Validation completes before the mutable workspace is opened or created. Schema, logical-key, and
source-open failures therefore leave no `.vqapr` directory in a fresh project.

`data.datasets.validate()` now checks that `DatasetRegistration.source` matches
`SourceSpec.source_id` before opening parquet. This is a registration-contract check rather than a
workspace concern. The workspace keeps its defensive mismatch check for internal callers, but the
documented facade reports `dataset.register.schema.source_mismatch` before I/O or mutation.

## Alternatives and trade-offs

- **Document internal imports** was rejected because internal paths would become compatibility
  contracts and architecture 2.6 explicitly names `vqapr.public` as the only documented surface.
- **Re-export from package `__init__.py`** was rejected because the canonical entry point is the
  explicit `vqapr.public` module.
- **Accept raw dictionaries or many scalar parameters** was rejected because the architecture
  already assigns physical and semantic declarations to `SourceSpec` and `DatasetRegistration`.
- **Return a new registration-result dataclass** was rejected for this minimal slice. The approved
  boolean already makes new-versus-idempotent behavior observable, while validation failures carry
  structured evidence.
- **Add the CLI now** was deferred. The handoff explicitly places `cli/data.py` as a thin later
  wrapper over this operation.

## Evidence and validation

The boundary test was written first and initially failed during collection because the empty
`vqapr.public` exported none of the required names.

After implementation:

```text
uv run pytest -q tests/boundaries/test_public.py tests/data/test_datasets.py tests/test_workspace.py
-> 36 passed in 0.88s

uv run python scripts/evidence_public.py
-> consumer_vqapr_import=vqapr.public
-> distinct processes returned changed=True then changed=False
-> persisted_across_processes=true
-> schema and weak-key failures returned mutation=false with workspace_exists=False
-> source mismatch returned dataset.register.schema.source_mismatch
-> the nonexistent mismatched source path was not opened or created
```

Completion validation:

```text
uv run pytest -q
-> 70 passed in 1.40s

uv run pytest -q -m "not real_data"
-> 66 passed, 4 deselected in 0.90s

uv run pytest -q tests/data/test_datasets.py tests/boundaries/test_public.py
-> 20 passed in 0.84s after final formatting

uv run ruff check src tests scripts
-> All checks passed

uv run ruff format --check src tests scripts
-> 148 files already formatted

uv run python -c "from vqapr.public import ..."
-> DatasetRegistration SourceSpec VqaprError register_dataset

uv build
-> built dist/vqapr-0.1.0.tar.gz and dist/vqapr-0.1.0-py3-none-any.whl

public import with the wheel prepended to sys.path
-> register_dataset.__module__ == "vqapr.public"

git diff --check
-> passed; Git emitted only the checkout's LF-to-CRLF warning for public.py
```

## Remaining limitations and follow-up

- This slice exposes registration only. Public lookup, requirement discovery, Model operations,
  and the CLI remain later slices.
- A first successful registration currently creates an empty workspace and then replaces it with
  the full declaration. True transaction coordination and crash recovery between those writes are
  not introduced here.
- Registration still performs a full logical-key scan on every equal retry before returning
  `False`; a safe cached-validation identity would require a separate provenance design.
