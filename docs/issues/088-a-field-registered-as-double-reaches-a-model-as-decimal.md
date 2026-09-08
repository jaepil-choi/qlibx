# 088 — A field registered as `DOUBLE` reaches a model as `Decimal`, because nobody declared what it is

**Status: CLOSED 2026-09-08 -- record `173`.** A dataset declares `field_types`; registration
compares the declaration with `DESCRIBE` once and refuses a mismatch by name; `DECIMAL` is a
measured type that no declaration may carry, so a decimal128 column is refused at registration
and a `Decimal` DataModel output at its first session. The sample panel writes float64. Ruling
below, as filed.

**Ruling 2026-09-08 by owner.** *"The framework does not declare a schema. The user declares one
and attempts to register. The framework verifies, once, at registration, that the declaration
matches the file. If it does, registration succeeds."* Confirmed against PRD §4.0: the user
already prepares the parquet (`sources.py:23`, "형식은 parquet뿐이다"), so the user declaring
its types is the same contract `available_at` has carried since the beginning -- the contract
names the type, the user prepares, the package judges. **This reverses two earlier rulings**:
`049`'s "author never writes a type; `DESCRIBE` is the only honest answer" (types are still read
off `DESCRIBE`, but as the thing the declaration is compared against, not as the declaration),
and `079`'s rejection of option A for a declared schema, which was argued from "a type system in
the declaration the author did not ask for" -- the author asked for it here.

**Found 2026-09-08** while tracing `vqapr show dataset sample-prices` for the 0.6.0 scenario
stepper: the envelope said `field_types: {close: DOUBLE}` and, on the same line, printed
`close: "78600.0000"`. The parquet is `decimal128(18,4)`.

## What happened

Three layers, each correct on its own terms, composing into a lie.

1. **Registration measured, and measured coarsely.** `scan._normalize` folded every `DECIMAL(p,s)`
   into `ColumnType.DOUBLE` (`scan.py:75`). The registration therefore recorded `DOUBLE` for a
   column that was not one, and since `049` the recorded value was a *measurement* nobody could
   contradict.
2. **The store hands a model whatever the file holds.** `store.py` deliberately converted
   nothing ("a conversion either way would be this package deciding how precise somebody else's
   measurement is"), so the `DOUBLE` field arrived as `Decimal`. Every scaffold and the SKILL
   compensated with `Decimal(str(value))` on every cell, because a model could not know which of
   two numeric types it would be handed -- the defect `051` describes from the other side, where
   a decimal fixture hid a float bug from 691 tests.
3. **The sample panel was the one parquet a user would never produce.** `tests/sample/build.py`
   wrote prices as `decimal128(18,4)` on the reasoning that prices should stay exact. So every
   test, walkthrough and showcase ran on `Decimal` while every real file is float64.

Money is `Decimal` on purpose (`account/`, `exchange/`, `analysis/`; `execution_table.py:375`
converts a price once, explicitly, at the boundary). The defect is only that the *data plane*
carried two numeric types and the registration could not say which.

## What the stages own

| stage | before | after |
|---|---|---|
| dataset registration | measures a type class, folds DECIMAL into DOUBLE, records it | takes `field_types` from the author, refuses `field_decimal`, `field_type_mismatch` by name |
| DataModel output | first session's arrow schema becomes the dataset (`079`) | producer states `field_types` from that schema; a non-declarable one is `datamodel.output.field_type` at the first session |
| StrategyModel | `Decimal(str(v))` on every cell to survive either type | a DOUBLE field is a `float`; `Decimal(str(v))` is the one deliberate crossing into the intent's arithmetic |
| execution | converts a price at the boundary | unchanged |

## What was decided, and what is still open

- `field_types` is a sibling map of `fields`, not `fields: {name: {expr, type}}`. It was already
  the on-disk shape (`DatasetCodec`), so a workspace written under the measured regime decodes
  as declared -- what duckdb measured is what the author would have written.
- `DECIMAL` is measured but not declarable. Reversible by adding it to
  `scan.DECLARABLE_FIELD_TYPES`; the reason not to is the whole of this file.
- A registration written before `field_types` existed is quarantined like one written before
  `grain` (`require_declared`): it opens, lists, removes and re-registers, and every read on it
  is refused with `dataset.register.schema.undeclared`.
- **Open:** a DataModel's `value_fields` stays a list of names. The producer states the types
  from what it wrote, which is honest but is the framework inferring rather than the author
  declaring. Whether `value_fields` becomes `name: type` is the same question as this file's,
  asked of user code rather than of a user file; not decided here.
