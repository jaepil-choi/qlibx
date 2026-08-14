# Persist project dataset declarations across commands

## Why this change exists

Dataset validation ended with an in-memory `DatasetRegistration`. A later command could not recover
that declaration, so `register -> process exit -> reopen` lost the project configuration. This left
the architecture's project-scoped workspace responsibility unimplemented and would force later
commands either to repeat declarations or introduce implicit global state.

## Outcome

An explicitly selected project root now owns `.vqapr/workspace.yaml`. A `Workspace` can be created,
opened in another process, queried for registered datasets, and extended one declaration at a time.

For an existing `dataset_id`:

- an equal declaration is an idempotent no-op and returns `False`;
- a different declaration raises `workspace.dataset.register.conflict` with `mutation=false` and
  preserves the existing file.

Missing and malformed workspace files fail through the existing `VqaprError.as_dict()` surface.

## Responsibility and flow

`src/vqapr/workspace.py` owns only project declaration persistence and lookup. It does not open the
declared parquet or repeat schema/key validation; those responsibilities remain in
`data/scan.py` and `data/datasets.py`.

The flow is:

```text
validated DatasetRegistration
  -> explicitly constructed Workspace(project root)
  -> .vqapr/workspace.yaml
  -> Workspace.open(project root) in a later process
  -> detached DatasetRegistration
```

The module does not inspect the current working directory and does not expose a process-global
workspace. Writes use a temporary file in the workspace directory followed by replacement so a
partially written YAML document is not exposed by the normal write path.

## Alternatives and trade-offs

- **Always overwrite an existing ID** was rejected because the same dataset name could silently
  change meaning.
- **Reject every repeated registration** was rejected because agents commonly retry the same
  operation; an equal declaration has the same identity and should not create a failure or rewrite.
- **Add replace semantics now** was rejected because replacement and its audit behavior were not
  approved for this slice.
- **Use process-global initialization** was rejected because two project instances in one process
  must not see each other's declarations.

The current YAML contains only `DatasetRegistration` values. Component, calendar, Exchange, source
configuration, public facade, and CLI persistence remain outside this slice. Concurrent writers are
also not coordinated; this implementation covers sequential commands and process-boundary reload.

## Evidence and validation

Development data was regenerated first:

```text
uv run --with pytz python scripts/prepare_dev_data.py
-> data/vqapr-dev/price_daily, 220 MB, 12 partitions, year=2015..2026
```

The user-facing evidence command:

```text
uv run python scripts/evidence_workspace.py
```

observed:

- real-data schema and full key validation passed;
- separate writer and reader PIDs recovered an equal declaration;
- two datasets survived reopen;
- equal re-registration returned `changed=False`;
- conflicting re-registration returned `mutation=false` and the stable conflict code;
- missing and malformed workspaces returned structured errors;
- two explicit project roots retained disjoint dataset lists.

Completion validation:

```text
uv run pytest -q
-> 53 passed in 0.99s

uv run pytest -q -m "not real_data"
-> 49 passed, 4 deselected in 0.44s

uv run ruff check src tests scripts
-> All checks passed

uv run ruff format --check src tests scripts
-> 146 files already formatted

uv run python -c "import vqapr; from vqapr.workspace import Workspace; print(Workspace.__name__)"
-> Workspace

uv build
-> built dist/vqapr-0.1.0.tar.gz and dist/vqapr-0.1.0-py3-none-any.whl
-> wheel contains vqapr/workspace.py

git diff --check
-> passed; Git emitted only the checkout's LF-to-CRLF warning for workspace.py
```

## Remaining limitations and follow-up

- Slice 5 still needs the documented public `register_dataset()` facade. CLI work remains later.
- Later declaration kinds must extend the workspace without making callers construct one giant
  configuration object.
- Run startup must freeze the declarations it consumes and must not reread the mutable workspace.
- Replace semantics and concurrent-writer coordination require separate explicit design decisions.
