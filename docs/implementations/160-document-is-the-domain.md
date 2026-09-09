# 160 — document is the domain: one pydantic shape per declared thing, one door, one place per rule

**Closes:** `docs/issues/archive/027`, `082`. **Branch:** `step-05-document-is-the-domain`, off
`develop @ 9cbc859e`. **Campaign:** `docs/refactoring/2026-09-04-the-one-shape-campaign.md`,
Step 5 (owner decisions D1·D2·D3); ExecPlan section M5 in `.agent/plans/active/one-shape-campaign.md`.
**Authority:** the owner, 2026-09-04 (D1–D3) and 2026-09-07 (milestone order: the merge before the
door; recorded in the ExecPlan).

## Why this exists

Campaign §1.3, in one sentence: a declared thing had two shapes — a pydantic document on disk and a
dataclass in the domain — with a mapping between them, so every rule about the thing was written
twice and could drift. `RunDocument.to_domain()` built a `RunDefinition` whose `__post_init__`
re-checked what `RunDocument`'s validators had checked; five `Workspace.register_*` doors stood
beside five `Transaction.register_*` doors; and `declarations.py` still carried prose generators
from before pydantic. Step 5 keeps one of each.

It was measured before it was started (ExecPlan M5, 2026-09-07): 764 + 336 + 445 lines across the
two files, ~130 direct-door call sites, 41 positional `StrategyEntry(...)` sites. **The cost of this
step is test churn, not source** — pydantic models are keyword-only, and a deleted door turns a
one-line registration into a block — which is what made the work safe to do in bulk and worth
measuring per milestone.

## What changed, by milestone

### M5b — the last hand-parsed section gets a model; the campaign was wrong about the rest

§1.3 named seven `declarations.py` functions as "pre-pydantic error prose" to delete. **Six of them
are the implementation of `refusals_from`**, the `ValidationError → Failure` adapter the same table
says to keep: `_keys_present`/`_permitted_values` build the missing-key sentence, `_expected_members`
the closed-set one, `_shape_words` the wrong-type one, `_model_of`/`_mapping_value_model` walk the
model tree to the permitted keys at a path. Deleting them would have deleted the refusal quality
`017`/`019` bought. Only `_require_keys` was a leftover, and it was reachable from one line: the
`instruments:` section, the last one parsed by hand.

So `instruments:` got `InstrumentsDeclaration` in `workspace_document.py` and goes through
`refusals_from` like every other section, and `_require_keys`/`_required` went (~45 lines). It found
a defect on the way: the refusal written for the **retired** `instruments: {<id>: {tables: ...}}`
shape fired on *any* document without a `tables` key, so a reader who typed `tabels:` was told to
"remove the id line and lift `tables:` up one level" — advice for a mistake they had not made.
Narrowed to the shape it names; a typo now gets the permitted key set and the nearest spelling.

### M5c — the run family, `SourceSpec` and `ComponentRef` are one shape each

- **`RunDefinition`** is a frozen pydantic `BaseModel` in the *domain* shape (a tuple of entries
  carrying `component_id`; `execution_input_id`; a snapshot and a mode). A before-validator accepts
  the stored spelling (`strategies` keyed by id, `execution_input`, one `initial_account` block) and
  a plain serializer emits it, so `workspace.yaml` bytes did not move — pinned by
  `test_the_document_round_trips.py`. Its rules are validators; `timezone` became a required field
  (its `""` default only deferred the refusal to the zone check).
- **`StrategyEntry`, `DataModelEntry`** are pydantic *dataclasses*, so their 67 positional call sites
  did not move.
- **`SourceSpec`, `ComponentRef`** are frozen `BaseModel`s whose field order *is* the stored key
  order; `path` serializes as written, `config` as a dict, the id is excluded on dump.
- **Deleted:** `RunDocument`, `StrategyEntryDocument`, `DataModelEntryDocument`, `SourceDocument`,
  `ComponentDocument`, their `to_domain`/`from_domain`, and `_require_wall_time`. (`_require_id`
  was named here as deleted when this record was first written; it stayed, because the `Frozen*`
  still use it -- corrected in Step 6.)
  `_linked` and `write_workspace` read and dump the models directly.

**Not merged, by judgment:** `DatasetDocument` and `ExecutionInputDocument`. Their `to_domain` is one
`.of()` call and they carry no rule the domain also carries; what they carry is the on-disk shape of
*measured* fields (`span`, `field_types`, `aggregated`, the quarantine of a span-less entry) and two
**named refusals for retired on-disk shapes** (`offset_sessions`, the old fill schema) that
`Workspace._read` matches by sentence. That is a codec, not a duplicate, and `DatasetRegistration`
(779 lines, 82 `.of()` sites) is the wrong home for a refusal about 0.3.0 YAML. They stay, and Step 6
should rename them `*Codec` when it reshapes the file.

**Found on the way — a latent hole, closed before it opened.** pydantic's `model_copy(update=)` does
**not** re-validate, where `dataclasses.replace` re-ran `__post_init__`. Thirty test sites built
variants with `replace(definition, ...)` and relied on the rules firing (a naive `start`, a reversed
period, a half-declared account all came back "valid" under `model_copy`). `RunDefinition.replace(**changes)`
rebuilds through `model_validate`, and those sites call it. Source never used `model_copy`.

Two wordings for one rule (document's vs. domain's) were pinned by different tests three times; each
is one sentence now, carrying both phrases. Seven `TypeError` expectations on *shape* became
`ValidationError`: pydantic owns the shape, which is the point.

### M5d — deferred to Step 6 as its first milestone

`Frozen*` are preflight products, never on disk as themselves: identities are hashed from explicit
payload dicts, and records pick fields by name (`record_fields`; nothing `asdict`s a frozen object).
D1 says "declared or on disk ⇒ pydantic"; they are neither. The only stated reason to convert them
is so Step 6's record models can `model_dump` them — a consumer Step 6 has not designed. The
sequencing constraint "5 before 6" holds as "6a before 6b".

### M5e — `register` speaks, a dataset names its producer, a list can be asked who reads

`027` was reopened by the owner with one question: why does nothing put the `available_at`
question to an author at registration? The rule settled in the issue -- **one sentence per
point-in-time concept, or nothing** -- is now `register`'s `spoken`, beside `registered`. The
sentences live on the declarations themselves: `DatasetRegistration.spoken()` (a row is knowable at
its `available_at` value and never earlier), `ExecutionInputRegistration.spoken()` (what `trade_at`
is a fact about; and how a decision fills -- `selector`, `at`, `timezone`, `trade_price` in one
sentence, because apart they mean nothing), `RunDefinition.spoken()` (when every model is called and
that it sees only rows knowable before then). `_apply` collects them; `apply()` returns a `dict`
subclass carrying `.spoken`, so its nine callers that index the mapping are untouched. A
components-only declaration says nothing.

`082`, both halves. **`produced_by`** on `DatasetRegistration` (and its codec, absent when `None`,
so existing bytes hold), set by `DataModelOutput.register` from the `run_id` the constructor now
takes and reported by `show dataset`/`list datasets`; a dataset from the author's own file names no
run. **`list components --reads <dataset-id>`** loads each strategy, datamodel and constraint in
this one process and keeps those whose `inputs()` name the dataset, with `reads: {<dataset>:
[<fields>]}` on the row. No index and no new field: the issue's 36 seconds were 41 *process starts*,
not 41 loads, and `show model` already loads one per process.

### M5a — one door

The five direct `Workspace.register_*` doors are gone; `Transaction.register_*` is the door, and
`Transaction` is a context manager (`with Workspace.transaction(root) as t: t.register_run(d)`),
committing on a clean exit and writing nothing on an exception. `declarations.register_dataset`/
`register_execution_input`, `extension.registration.register_component` and
`DataModelOutput.register` stage and commit through it.

Measured before starting: 117 statements in tests, 115 rewritten by an AST pass (receiver
`Workspace.create/open(root)` or a bound name; `Expr`/`Assign`/`Assert` forms), 2 correctly left
(`vqapr.public.register_dataset`, already the right door), 1 in a worker-process source string
fixed by hand -- 19 files. No new `E501`s; ten `SIM117`s from nesting `with pytest.raises` over the
new block, merged.

**Three guarantees the direct doors had, which the one door had to keep -- each surfaced as a test:**
a caller holding a `Workspace` sees what it just registered (`Workspace.transaction(workspace)`
stages against and refreshes *that* object); a fresh project's first registration writes the
document (`commit()` writes when the transaction began from a root with no document -- a roster
alone is a workspace); and a document that has *vanished* since the workspace was opened refuses
by name, `workspace.open.missing`, rather than being quietly recreated (freshness is decided by
who started the transaction, not by whether the file exists at that moment).

**Process note, the miss.** The caller count taken before M5a listed `src/vqapr/public.py: 2`, and
the AST rewriter was scoped to `tests/`. The two public helpers (`public.register_component`,
`public.register_run`) kept calling the deleted doors, every targeted test run passed -- none of
them use the public helpers -- and the first full run failed 34 times, every failure a showcase or
a slow journey. A caller count is not a rewrite scope: the fix was two lines, the lesson is that
deleting a door is a change to run assembly and wants the showcase gate *before* the full suite,
the way Step 4's module deletion wanted `--collect-only` first.

## Measured

| | after Step 4 (`9cbc859e`) | after Step 5 |
|---|---|---|
| modules under `src/vqapr` | 125 | **125** |
| lines under `src/vqapr` | 31,647 | 31,766 |
| document/domain pairs with a `to_domain` | 6 | **0** (two codecs remain, by judgment) |
| direct `Workspace.register_*` doors | 5 | **0** |
| files changed | — | 43 (+1,427 / −1,222) |

The source line count rose by 119 while ~1,200 lines left: the validators that lived in
`__post_init__` and the document models moved *into* the surviving models, and `RunDefinition`
gained `replace()` and `spoken()`. What went was the second copy — the mapping layer and the five
doors — not lines. Collection: 1419 → 1425 (M5b −1, M5c +3, M5e +4).

## Validation

- `uv run ruff check src/` — clean on every touched line (three pre-existing `E501`s in
  showcases untouched).
- `pytest --collect-only` after each deletion: 1419 → 1418 (M5b) → 1421 (M5c) → 1425 (M5e).
- Per milestone, the affected files: M5b 384 passed; M5c 90 + 264 + 402 (`cli`+`flow`) passed;
  M5e 93 passed; M5a 94 passed after the three guarantees were restored.
- `uv run pytest tests/ -q -m ""` — **1422 passed, 3 failed** in 861s. Two were the deferred-import
  ratchet (`tests/boundaries/test_a_deferred_import_states_its_reason.py`): `list_.py::_reading`
  had added two function-local `vqapr` imports, taking the count to 20 over a ceiling of 18.
  Hoisted to module level (no cycle; `vqapr.cli.main` imports cleanly), ratchet and the CLI files
  re-run green (30 passed). The third is the documented `test_five_processes_racing_...` flake,
  2 of 3 in isolation after. The first full run had failed 34 times on the `public.py` miss
  recorded above; the four files it named were re-run green (28 passed) before this run.
- The byte-identical gate (`test_the_document_round_trips.py`) and the on-disk pins in
  `test_workspace.py` passed at every milestone.
