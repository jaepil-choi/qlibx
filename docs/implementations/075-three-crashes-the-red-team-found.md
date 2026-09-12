# 075 — Three crashes the red team found

Slice B's completion gate drove the six new behaviours against hostile input and found three
`stage: "unhandled"` bare-exception crashes. All three are the defect class this whole slice exists
to remove, reached by inputs a real project produces.

## A registered roster whose tables are gone

Delete a roster's backing parquet between registration and the run:

```
{"ok": false, "stage": "unhandled", "error": "FileNotFoundError: ...instruments_stock.parquet"}
```

`_registered_roster` guarded only the pointer lookup; the `read_roster_table` calls that open the
actual files were unguarded. `cli/list_.py` handles the same failure — the same slice added that —
so one path degraded and the other crashed.

**`run` refuses, and does not degrade.** That asymmetry is the decision worth stating:

- `list instruments` is the orientation command. A moved table should reduce the answer, not remove
  it, so it reports `unreadable` and still gives the digest and declared tables.
- `run` is about to charge and size every fill. Continuing without categories would produce a
  complete, reproducible book computed as if nothing had a category — silently, because a run with
  no roster at all is legal and completes.

```
run.roster.unreadable
requirement: a registered instrument roster must be readable at run start, because every fill is
             charged and sized against the category it declares
observed   : instrument table is missing: .../instruments_stock.parquet (declared tables: ...)
fix        : restore the roster tables at the paths above, or re-register the roster with
             `vqapr register <instruments>.yaml`; `vqapr list instruments` shows what this
             project has registered
```

## A corrupt roster pointer

Corrupt `.vqapr/instruments.json` and `vqapr list instruments` raised a raw `JSONDecodeError`. The
parse happens inside `Workspace.registered_instruments()`, **before** `list_.py`'s own guard, which
only wraps the table reads.

Fixed at the source, as `workspace.instruments.unreadable`. Reported, never repaired and never
treated as absent: *no roster* and *a roster whose record is damaged* are different states and only
the first is ordinary.

`cli/list_.py`'s workspace-absent guard in `run()` already holds that line for the workspace
document itself. Its comment says an absent workspace is an empty one, but a corrupted workspace
must keep failing loudly, because catching `Workspace.open` broadly would erase the distinction and
report damage as zero items. This is the same rule applied to its sidecar.

*Cited by construct rather than by line, deliberately. Every citation in this record that carried a
line number has been wrong once — including the correction to this very sentence, which landed five
lines above the comment it meant. The two that named a construct have been right throughout.*

## An id that cannot name a class

`vqapr new constraint '123-not-a-valid!'` emitted a file whose class name was `123NotAValid!`, then
failed re-reading its own output with a `SyntaxError`. Not constraint-specific — `new strategy` and
`new datamodel` did the same, since `_class_name` only split on `-`/`_` and title-cased the parts.

It checks `str.isidentifier()` now, before anything is written, and the CLI renders the refusal as
`cli.input.value_invalid` naming what an id may contain and giving an example. The check lives in
`_class_name` because that is the one place that knows what the id has to become.

## Four smaller findings from the same gate

- **The undeclared-table receipt globbed too widely.** It derived a prefix from the declared files
  and then matched `{prefix}_*.parquet`, so `universe_prices.parquet` beside `universe_stock.parquet`
  was reported as an undeclared roster table. It iterates `InstrumentKind` by name now. Report-only,
  so the cost was a false line in a **success** receipt — which is the one place a false line is
  least likely to be checked.
- **The emitted instruments declaration restated the category vocabulary** as a literal
  `("stock", "etf", "index", "factor")`. It iterates the enum now. A fifth category would have been
  registrable, would have appeared in the refusal text derived from the enum, and would have been
  silently absent from the emitted declaration — landing an author in exactly the undeclared-table
  case the same command reports after the fact.
- **`list_.py` had two imports inside its broad `try`,** so an `ImportError` would have been
  reported as `unreadable: No module named ...` on a row that otherwise looked healthy — a
  packaging defect wearing a data-availability label. Hoisted out; they perform no I/O.
- **The KRX scaffold's comment claimed a run states which price-limit setting it measured.** It
  does not: `price_limit_rate` reaches `TradeRule.declaration_identity`, but `FrozenRun`'s identity
  folds the exchange as `(component_id, fingerprint)` and never calls it. Reworded to what holds —
  the setting is in the file the record fingerprints as `source_digest`, recoverable by reading the
  venue at that digest, and not a field in `show run`.

## Two more, one layer deeper

Re-driven against neighbouring inputs, two of the three fixes turned out to guard one layer short.
Both are recorded because the pattern is the point: a guard placed at the shape of the failure you
saw stops the failure you saw.

**Valid JSON of the wrong shape.** Guarding `json.loads` left every reader indexing
`pointer["tables"]` and `pointer["digest"]` on a dict that might not have them, so
`{"schema": ..., "digest": ...}` with no `tables` moved the crash from the parse to the access.
`registered_instruments` now checks shape as well as syntax -- object, both keys present, `tables`
a non-empty object -- at the one door both `list` and `run` come through.

**`str.isidentifier()` returns `True` for keywords.** `None`, `True` and `False` are already
title-case, so the transformation leaves them untouched and they passed the new check to become
class names that will not parse. `keyword.iskeyword` is checked alongside it now. Lowercase
keywords were safe only by accident -- `class` becomes `Class` -- which is not a property to rely
on.

## A refusal that would have reported a completed run as failed

The first fix created its own edge, and the architect lane found it. `_registered_roster` now
raises, and `_roster_envelope` calls it **after** the run has finished and its record is on disk.
A roster whose tables vanish during the minutes a real run takes would have produced exit 1 for a
run that `run_ids` already lists -- the record and the command disagreeing about whether the run
happened.

It catches there and reports a warning clause on the success envelope instead, saying the run read
a registered roster, the roster became unreadable afterwards, and the frozen record states what the
run actually used. Refusing at run start and warning at envelope time is the same fact answered for
two different questions.

**The first version of that clause reported `known: false`, and both review lanes caught it
independently.** The run *did* know: `_registered_roster` refuses an unreadable roster at run
start, so any run reaching this envelope read its roster successfully, its fills carry real `kind`
values, and the frozen record carries the digest and counts computed while the tables were
readable. `known: false` is also what the genuinely-rosterless branch reports, whose note says
every fill records `kind: None` -- so a reader testing `roster["known"]` would have concluded the
exact opposite of the truth, from a field the docstring designates as the one that answers the
question. It is `known: true, stale: true` now: the run knew, and the counts could not be re-read.
The note and the field agree.

## One finding filed rather than fixed

`docs/issues/archive/013` — a venue's own `UNIVERSE` and the project's registered roster are two
independent statements about instrument category, compared nowhere. A run was produced where the
fill's `kind` said `stock` while the tax charged followed the venue's `etf`. Repairing it means
deciding which statement wins, and a `check`-side cross-check means a ninth judgment, which
`tests/cli/test_check.py` pins at eight with its own message saying that is a decision. Not Slice
B's to make.

A second was filed after this record was first written: `docs/issues/archive/014`. The constraint
scaffold's corrected semantics cited `SingleNameCap` as the shipped size-only precedent, and the
cleaner lane checked the citation rather than the claim -- `SingleNameCap`'s `project` floors at
`0`, its `validate_intended` measures raw signed weight, and its `evaluate` measures `abs`. It has
the same three-way disagreement the scaffold was just corrected for. The citation is reworded; the
shipped constraint is left alone, because changing which books a run accepts is a product decision
with its own test surface.

## Validation

```
uv run pytest tests/ -q      # 1312 passed, 14 deselected
```

All three crashes were reproduced through the CLI before the fix and re-driven after: each now
returns a structured `code`/`requirement`/`observed`/`fix` with a named stage instead of
`stage: "unhandled"`.

The refusal-code baseline gains `run.roster.unreadable` and `workspace.instruments.unreadable` in
`coverage_gap` — declared and not provoked by the characterization harness, which is accurate,
since both require a filesystem the harness does not damage. Nothing was removed from
`runtime_codes`.
