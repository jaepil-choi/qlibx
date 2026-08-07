# 039 Validate and execute project-local Strategy extensions

## Intent

Project-owned alpha code could be passed to `QlibxProject.invoke()` only as an already imported
in-memory object. The package could not validate a Strategy module, record the exact source and
fixture that passed, register project-local artifact payload models, or prevent changed source from
being executed under an old compatibility claim. The existing extension lifecycle proved these
properties only for one neutralization transform.

M3 adds a Strategy-specific lifecycle without turning neutralization arithmetic into a generic
plugin framework and without exposing the artifact backend to Strategy code.

## Observable outcome

A trusted `.py` file below the configured project extension root exposes fixed `STRATEGY_SPEC` and
zero-argument `create_strategy()` symbols. The package loads it under a source-hash identity, creates
two fresh Strategy instances, resolves their exact frozen dataset/artifact/state inputs, and compares
typed `StrategyDraft` plus all access evidence. Only a deterministic compatible module publishes a
`strategy_extension_registration:v1` artifact.

Project-local `QlibxModel` payload classes may be declared by one module-local symbol. Their artifact
type/version and JSON-schema hash are stored in the registration and used through an immutable
registration-scoped contract registry. Built-in collisions, dotted/import symbols, non-local models,
and schema drift are rejected. The process-global built-in registry is never mutated.

Runtime execution accepts only an exact registration artifact ID. It hashes the registered file
before importing it, reconstructs and compares the fixed module contract, injects the
registration-scoped artifact registry into the existing Research/Daily flows, and records the
registration as a dependency of every resulting Strategy artifact. Registered daily configuration
identity includes the exact registration and source hash, so a different registration cannot resume
as the same frozen run.

## Responsibilities and flow

- `extensions.local_modules` confines one trusted file to the project extension root, computes its
  source hash, and loads it under a private hash-derived module name. The neutralization flow uses
  the same helper while retaining its existing payload and identity.
- `extensions.strategy` owns portable Strategy extension spec, request, registration, local payload
  model, registered-handle, and validation-result contracts.
- `flow.artifact_inputs` owns an operation-scoped immutable contract registry. Built-ins are the
  default; a validated Strategy module receives a derived registry containing only its local models.
- `StrategyExtensionFlow` owns module-contract validation, requirement resolution, optional frozen
  checkpoint/session-performance materialization, two-instance computation, registration evidence,
  and failure publication.
- Validation-only execution constructs scoped views directly. It never publishes `StrategyResult`,
  creates decision intent, or enters Account/Strategy-memory commit paths.

## Frozen state fixture

The validation request can name an exact simulation-checkpoint artifact and an exact
session-performance artifact. The checkpoint restores Account, feedback, and the selected
Strategy's memory snapshot. Future-dated or incompatible evidence is rejected. If state evidence is
not selected, access to that view role fails rather than receiving a fabricated empty value.

Registration dependencies are derived from actual view access. A selected but unused artifact or
state fixture remains part of the recorded validation request but is not claimed as consumed
lineage.

## Failure contract

Module/path/import failures use `STRATEGY_EXTENSION_MODULE_INVALID`. Fixed symbol, identity,
factory, and requirement defects use `STRATEGY_EXTENSION_CONTRACT_INVALID`. Local payload model
failures use `STRATEGY_EXTENSION_ARTIFACT_MODEL_INVALID`. Invalid output or unavailable view inputs
use `STRATEGY_EXTENSION_VALIDATION_FAILED`; different declarations, drafts, or access evidence from
fresh instances use `STRATEGY_EXTENSION_NONDETERMINISTIC`.

Exact reload failures use `STRATEGY_EXTENSION_REGISTRATION_INVALID`,
`STRATEGY_EXTENSION_LOAD_FAILED`, `STRATEGY_EXTENSION_SOURCE_DRIFT`, or
`STRATEGY_EXTENSION_CONTRACT_DRIFT`. Source hash is checked before import, and no execution path
searches for a latest or compatible registration.

Dataset resolution retains package requirement errors. Artifact resolution retains the M2
`STRATEGY_ARTIFACT_*` family under the Strategy-extension validation operation identity. Every
failure has `commit_status=NONE` and cannot produce a registration or Strategy success artifact.

## Alternatives and trade-offs

Executing a module once and registering its source hash was rejected because hidden singleton or
module-global state could pass. Two fresh instances catch deterministic-contract drift for the
recorded fixture, but this remains fixture evidence rather than formal branch coverage.

A mutable global payload registry was rejected because one project could silently redefine another
project's artifact meaning. Registration-scoped registries make the selected source and schema part
of execution identity.

This lifecycle does not sandbox Python or install dependencies. Project-local code is trusted user
code; path confinement and hashing provide integrity, not hostile-code isolation.

## Validation

Initial M3 validation slice:

```
.venv/Scripts/python.exe -m pytest tests/test_strategy_extensions.py tests/test_strategy_artifact_inputs.py tests/acceptance/test_extension_scenarios.py tests/test_architecture.py -q -p no:cacheprovider --basetemp C:\tmp\qlibx-pytest-m3-validation-019fd94d
-> 26 passed in 4.50s
```

The focused suite covers deterministic registration, invalid paths, singleton factory,
nondeterministic output, registration-scoped custom payload consumption, built-in collision,
state-fixture access, M2 artifact regressions, neutralization regression, and architecture layering.
Full validation before the registration-validation commit:

```
.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp C:\tmp\qlibx-pytest-m3-validation-full-019fd94d
-> 199 passed in 115.92s

.venv/Scripts/python.exe -m ruff check <changed Python files>
-> clean
```

Registered execution validation:

```
.venv/Scripts/python.exe -m pytest tests/test_strategy_extensions.py tests/test_strategy_artifact_inputs.py tests/test_public_daily.py tests/test_cli.py -q -p no:cacheprovider --basetemp C:\tmp\qlibx-pytest-m3-execution-new-019fd94d
-> 46 passed in 25.59s

.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp C:\tmp\qlibx-pytest-m3-execution-full-019fd94d
-> 205 passed in 130.98s
```

The slice proves exact-ID research and daily execution, registration lineage, registration-scoped
payload deserialization, source-drift rejection before compute, CLI validate/list, and curated
installed-Strategy imports. Build and fresh-wheel sample evidence is added in the final M3 commit.

## Remaining limitations

- Installed template, PRD/Architecture closure and fresh-wheel evidence remain in the final M3
  documentation/sample commit.
- Ensemble multi-source state/cursor semantics and `StrategyResult` schema remain M4 scope.