# 002 Project registration and evidence foundation

## Why

qlibx needs a safe first-user boundary before research or execution exists. A project must preview
owned changes, register only confirmed data meaning, discover downstream requirements
progressively, and preserve both success and failure evidence without silent overwrite.

## Outcome

- QlibxProject initializes and opens an explicit project root; initialization previews by default
  and refuses to overwrite a different qlibx.yaml.
- DatasetRegistration validates user-selected instrument, availability, logical key, source
  fingerprint, and optional semantic bindings without requiring unrelated metadata.
- RequirementResolver reports operation-scoped missing capabilities without mutating registration.
- LocalArtifactBackend atomically indexes immutable JSON payloads and dependency edges in DuckDB;
  logical identity conflicts fail and unindexed payloads remain invisible.
- A version-matched qlibx skill is bundled in the wheel and can be previewed/applied independently
  to Codex, Claude, or an explicit custom root without overwriting user modifications.
- The CLI exposes only implemented project, registration, onboarding, and artifact-list behavior.

## Responsibility and flow

The package validates observed facts and emits structured errors. The bundled skill explains
recovery choices, but availability and other economic meanings remain user decisions. Successful
registration is append-only. Artifact publication validates a typed payload, writes content, then
commits envelope and lineage visibility in one DuckDB transaction. Onboarding owns only generated
skill files and a marked instruction block.

## Alternatives and trade-offs

Registration storage is immutable JSON per logical dataset while reusable artifacts use DuckDB.
This keeps the first registration contract inspectable; a later backend may unify indexing without
changing RegisteredDataset identity. YAML input is passed through Pydantic JSON-validation mode so
enum and tuple wire representations are accepted while strict numeric/string coercion remains
disabled. No source field name is treated as semantic evidence by itself.

## Validation

- uv run pytest -p no:cacheprovider --basetemp <task-path> -q: 28 passed.
- uv run ruff check src tests: passed.
- skill-creator quick_validate.py src/qlibx/resources/skills/qlibx: Skill is valid.
- uv build: built qlibx-0.1.0 sdist and wheel.
- Wheel inspection confirmed SKILL.md, agents/openai.yaml, error-recovery.md, project, onboarding,
  data, and evidence modules are included.
- git diff --check -- src tests docs/implementations: passed with the expected line-ending warning.

## Remaining limitations

The current registry validates and records availability but no runtime view reads observations yet.
Only JSON model artifacts are published; Parquet table payloads arrive with research artifacts.
No Strategy, execution, Account, monitoring, or OMS behavior is implemented in this slice.
