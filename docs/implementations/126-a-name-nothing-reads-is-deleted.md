# 126 — a name nothing reads is deleted

## Why this exists

`ruff` is file-local by construction. `F401` sees one module's imports and `F841` sees one
function's locals, so nothing in the configured rule set can answer the question a cleanup
actually asks: *is this method called anywhere*. Record 105 made the configured gate a declared
command; it still could not see across a module boundary.

The cross-module pass was added in the commit before this one and reported 35 names. Twenty of
those were the tool being wrong in three predictable ways — a method the interpreter or a
framework calls by protocol, a class a registry resolves from a string literal, and a frozen
dataclass field written at construction and read only by serialization. Those are recorded with
their callers in `scripts/vulture_whitelist.py`. Record 124 then deleted four more of them along
with the modules they lived in.

This record is the remainder: names with no reader anywhere in `src/`, `tests/`, `scripts/`,
`showcases/` or `docs/`, each confirmed by hand rather than by the tool's confidence score.

## What changed

**Deleted from `src/` (11 names):**

| Name | File | Why it had no reader |
| --- | --- | --- |
| `account_fields`, `instrument_fields` | `account/history.py` | A pair of properties splitting `AccountRequirement.fields` by category. `__post_init__` validates against `ACCOUNT_FIELDS` and `INSTRUMENT_FIELDS` directly, so the split was never consumed. |
| `configuration_id`, `ConfigurationId` | `domain/identifiers.py` | The constructor and the `NewType` it was the only user of. Six sibling id constructors are live; this one never acquired a caller. |
| `REQUIRED_FIELDS` | `domain/roster.py` | A duplicate. `roster_export.py:98` enforces the same contract from an inline `(INSTRUMENT_ID_FIELD, KIND_FIELD)`, and those two constants stay. |
| `instrument_types` | `domain/roster.py` | A re-export wrapper around `INSTRUMENT_TYPES`. Both real consumers — `instruments.py` and `exchange/listings.py` — import the mapping directly. |
| `model_states` | `flow/run_state.py` | A read-only projection of `_model_states`. `load_model_state` is the door callers use. |
| `PlanningEvidence` | `flow/simulation.py` | A frozen dataclass with a validating `__post_init__` that nothing ever constructed. |
| `COMPONENT_REGISTER_STAGE` | `workspace.py`, `workspace_codec.py` | Declared in both files. Record 064 retired the `workspace.component.register.*` refusal codes; `tests/characterization/refusal_codes.baseline.json` carries only the `lookup` pair, so the constant these were folded from has had no reader since. |
| `_stale_lock_age` | `workspace.py` | Private, no caller. `_internal/filelock.py:14` mentions it only as history — the two implementations disagreed about a negative age and the other one won. |

**Renamed:** `flow/run_records.py`, the `taken` callback's parameter to `_error`. It is required by
`atomic.write_atomically`'s `on_error: Callable[[OSError], BaseException]` contract and
deliberately unread, which is a different fact from dead code and should read as one.

**Deleted from `tests/` (2 names and their now-orphaned imports):** `NY` in
`acceptance/test_time_002.py` and `_account_state` in `flow/test_acceptance.py`.

## Trade-offs

**`REQUIRED_FIELDS` carried a docstring the inline tuple does not.** It described why both shipped
instrument categories are field-free and what a category carrying its own facts would add. That
prose is lost here. Wiring `roster_export.py` onto the constant instead of deleting it would have
kept it, but that changes a working enforcement path to save a comment, and the comment describes
a design that is documented in `docs/vqapr-architecture.md` anyway.

**Two names are knowingly left behind.** `_encode_requirement` and `_decode_requirement` in
`workspace_codec.py` have no caller, but
`tests/boundaries/test_the_codec_moved_and_the_refusals_did_not.py:119` asserts they exist by
name — `f"def {marker}(" in source` — as part of a placement contract. Deleting them means
deciding what that assertion is for, which belongs with the Workspace/codec cleanup that owns
that file, not here. The pass reports exactly these two and nothing else.

## Validation

- `uv run vulture` — 15 reports before, **2 after**, both the deliberately retained pair above.
- `uv run ruff check src/` — clean. Four imports orphaned by the deletions were removed with them
  (`INSTRUMENT_TYPES` in `roster.py`; `Decimal`, `AccountSnapshot`, `AccountState` in
  `flow/test_acceptance.py`). Two pre-existing findings in `acceptance/test_time_002.py` (`I001`,
  an unused `ModelStateRef`) were confirmed present before this change and left alone; `tests/` is
  not covered by the declared lint command.
- `uv run pytest tests/ -q -m ""` — **1287 passed**. The full set rather than the default, because
  `flow/run_records.py` is the record shape.

## What this did not do

No public surface moved: none of the eleven names appears in `vqapr/public.py`, and the CLI is
untouched. No behavior changed — every deletion is a name with no reader, and the one rename is
positional in its only call site (`on_error(error)`).
