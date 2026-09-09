# 145 — pydantic replaces the hand-written codec

**Closes:** nothing in `docs/issues/` by number; this is decision D3 of
`docs/refactoring/2026-09-03-the-deletion-campaign.md` (Step 4, C-1), made by the owner on
2026-09-03: *"pydantic, pyyaml이 있는데 이걸 reinvent할 필요 없어."* It is the first half of the
diagnosis S3 (god modules) for the workspace trio.
**Plan:** `.agent/plans/active/step-04-pydantic-replaces-the-codec.md` (moved to `completed/` with
this record). **Authority:** the `035` ruling's shape (validate at the boundary, once) applied to
documents; record `117` (the codec is one file) and record `129` (why pydantic left).

## Why this exists

YAML text was already parsed by PyYAML. What came after -- turning the dictionary into
dataclasses while checking key sets, scalar types, enums, ISO datetimes and Decimals, copying
every object on the way out so a caller could not mutate the workspace's copy, and reporting
every missing key at once -- was written by hand: `workspace_codec.py` (1,168 lines at the
campaign's baseline), the `_require_keys` / `_required` / `_mapping` / `_enum` / `_time` /
`_role` family in `declarations.py`, and `isinstance` checks by the dozen. That is a schema
library, and one was already in the tree once: record `129` removed `pydantic` because nothing
imported it. Removing an unused dependency was right; declaring one and using it is this record.

## What changed

- **`workspace_document.py` (new).** One pydantic model per YAML section, twice: the stored
  shape (`SourceDocument`, `DatasetDocument`, `ExecutionInputDocument` + `FillDocument`,
  `ComponentDocument`, `AgendaDocument` + `OccurrenceDocument`, `StrategyConfigDocument`,
  `RunDocument` + `AgendaReference` / `InitialAccountDocument` / `StrategyEntryDocument`) and
  the declaration shape (`DatasetDeclaration`, `TableDeclaration` + `FillDeclaration` +
  `ExecutionInputDeclaration`, `AgendaDeclaration`, `ComponentDeclaration`,
  `StrategyConfigDeclaration`; a run's declaration IS its stored shape). Every model is frozen
  and refuses an unknown key. `to_domain` / `from_domain` are the one place a shape is mapped
  onto the dataclass the engine uses. `WorkspaceDocument` is the whole file; `read_workspace`
  (memoized on the text's sha256, as before) validates it and links the forward references;
  `write_workspace` dumps it, sections sorted by id, empty ones omitted.
- **`workspace_codec.py` is deleted.** `_decode` (520 lines), `_encode`, the seven `_detach_*`
  copies, `_run_instant`, the key-set constants. The frozen dataclasses were never mutable; the
  copies were guarding against nothing. The stage constants and lock/swap constants it also
  held were already duplicated in `workspace.py`, where the refusal inventory needs them.
- **`declarations.py`.** `_dataset`, `_execution_input`, `_agenda`, `_component` and the
  `strategy_configs` / `runs` loops read through the declaration models. Gone: `_require_keys`,
  `_required`, `_time`, `_role`, `_source`, `_DATASET_KEYS`, `_AGENDA_KEYS`,
  `_require_agenda_keys`. Kept, on purpose: `_require_grain_key` (design §7-3's sentence about
  what `RowsLookback` now means), `_enum` (the closed-set refusal `docs/issues/archive/017` asked for,
  still judging a run's `initial_account.mode` before the model so the reader gets the whole
  set and the nearest member), the agenda's from_dataset/sessions pair (no required-key list
  can say "exactly one of"), path resolution against the declaration file, and the `ast` walk
  for a component's sole subclass.
- **`refusals_from(error, model=, name=, also=)`** is the adapter: every pydantic line error
  becomes one `Failure` with this package's code, a `fix` that says what to write, the
  `DECLARATION_SHAPE` topic and a `source` at the dotted key path, and all of them travel in
  one `Diagnosis` -- the property `_require_keys` promised. A missing key names what the
  declaration does have and, for a closed-set field, its vocabulary; an unknown key
  (`declaration.read.key_unknown`, the one new code) and a value outside a closed set get the
  nearest permitted name; everything else is `value_invalid` at its own path. Nothing pydantic
  wrote reaches the envelope (`tests/test_a_validation_error_is_a_refusal.py`).
- **`workspace.py`.** Imports `read_workspace` / `write_workspace` and nothing else from the
  document module. `_merge_declaration` and `_config_lookup` lose their `detach` parameter.
  The per-kind `register_*` / `_merge_*` stay: each carries that kind's reference rule, which
  is the part that was never a codec.
- **Legacy shapes, all in one file.** The old fill schema without DST proof and the retired
  `offset_sessions` key (refused by name, as before, and `Workspace._read` still surfaces those
  sentences), the agenda-keyed strategy config (read for one release, record `138`), the
  span-less and type-less dataset entries (quarantined, not refused), and the two sections
  record `144` retired (read and dropped). The boundary test that pinned the codec file now
  pins this one.
- **`pyproject.toml`.** `pydantic>=2,<3` (resolved 2.13.5, pydantic-core 2.46.5); the comment
  that explained its removal now explains its return. `[tool.vulture]` ignores pydantic's hook
  decorators and `model_config`; the whitelist names the two read-and-dropped fields.

## What a user sees

Nothing new on a valid document: the same `workspace.yaml` bytes are written
(`tests/test_the_document_round_trips.py`), the same declarations register, the same refusals
come back with `fix` / `explain` / `source`. Two differences on an invalid one: an unknown key
inside a declaration body is now refused with the nearest permitted name (it used to be
ignored), and a wrong scalar type is named at its own path rather than as a sentence about the
whole entry.

## Validation

```
uv run ruff check src/                              All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -m "" -rfE      1352 passed, 1 failed (the detachment test, below; fixed in the next commit)
PYTHONUTF8=1 uv run pytest tests/ -q -rfE            1332 passed, 21 deselected  (after the fix; branch point: 1322 / 21)
PYTHONUTF8=1 uv run pytest tests/showcases -m ""    9 passed
uv run vulture                                      nothing new in src/ (pydantic hooks whitelisted by decorator)
uv build                                            dist/vqapr-0.3.0-py3-none-any.whl
python -m tests.characterization.refusal_codes      one code added: declaration.read.key_unknown
```

Branch point `develop @ bc77ca6d`. Ten tests added (the adapter's six, the round trip's two,
Step 3's three carried), none removed; `tests/flow/test_preflight.py`'s detachment test now
asserts the stronger property -- a registration's config cannot be edited at all -- instead of
mutating one and checking the copy did not move.

| | before (`bc77ca6d`) | after |
|---|---:|---:|
| `workspace_codec.py` | 1,035 lines, 60 `isinstance` | deleted |
| `workspace_document.py` | -- | 877 lines, 5 `isinstance` |
| `declarations.py` | 1,130 lines, 12 `isinstance` | 1,152 lines (the adapter is 150 of them), 11 `isinstance` |
| `workspace.py` | 1,659 lines, 18 `isinstance` | 1,644 lines, 18 `isinstance` |
| `flow/run.py` | 614 lines, 40 `isinstance` | unchanged: the runtime dataclasses were out of scope |
| `src/` diff | | 4 files, +1,245 / -1,396 |

The one behavioural fix the step forced: `ComponentRef.of` wraps `config` in a
`MappingProxyType`. The detach copies had been what kept a frozen run's binding apart from the
workspace's registration; without them the registration object itself has to be read-only, and
now it is.
