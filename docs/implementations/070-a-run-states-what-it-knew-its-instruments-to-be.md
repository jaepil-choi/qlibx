# 070 — A run states what it knew its instruments to be

A run with no registered roster completes with every fill recording `kind: None`. No refusal, no
warning, nothing in the success envelope. On an academic venue that is harmless. On a KRX-shaped
venue it means every name was charged identically while the record says the categories were never
known — and `cost_by_kind()` collapses to one unlabelled bucket, so the report that would expose it
is the one the gap erases.

## Two facts were computed on every run and thrown away

`_freeze_record` built `roster_digest` and `declared_digest`, and `RECORD_FIELDS` listed neither.
The writer's last line is

```python
writer.finish({field: builders[field]() for field in RECORD_FIELDS if field != "run_id"})
```

so a builder absent from that tuple is never called. Both were dead: computed, correct, and
dropped before reaching disk. Same shape as the `Fill.kind` column record `067` added — the object
was right and the record did not carry it, which is the class of defect a test at the object level
cannot see.

`RECORD_FIELDS` now carries `roster` and `declared_digest`. `cli/show.py` projects that tuple, so
`show run` surfaces both with no change of its own; the exact-set assertion in
`tests/cli/test_show.py` is updated in the same change, which is what stops the two sides drifting.

## What `roster` says

```json
{"digest": "...", "tables": ["etf", "stock"], "by_kind": {"stock": 10, "etf": 2}, "instruments": 12}
```

or `null`, which is the answer that matters. The per-category counts come from the roster already
loaded for this run rather than from a second read of the file, so what is reported is what was
bound to the venue, not what the file says now.

Stated, never compared. A roster grows as a matter of course — a daily batch lists new tickers,
issuers delist, a name is reclassified — so a run refused for reading a different roster than
yesterday would be refused every morning (issue `009`). What a run treated each instrument as is
testified to per fill by `Fill.kind`; this says which declaration produced those categories, and
`null` says the run never knew them.

The success envelope carries the same fact, always as a mapping so a reader testing it does not
have to distinguish *no roster* from *this version does not report one*:

```json
"roster": {"known": false, "note": "no instrument roster is registered, so every fill records
kind: None and cost_by_kind() collapses to one unlabelled bucket; register one with
`vqapr register <instruments>.yaml`"}
```

Reported on the **success** path on purpose. The run is legitimate; what was missing was a
statement of what it was computed against.

## Two registration refusals, at different layers

They are different things and both were worth closing.

**A table sitting beside the declaration that the declaration does not name.** The emitted
`instruments.yaml` ships `stock:` live and `etf:`, `index:` and `factor:` commented. An author who
exports twelve names across two categories and registers it unchanged registers **ten**, with the
ETF table sitting beside it undeclared. The receipt now names the file:

```json
{"instruments": 10, "by_kind": {"stock": 10}, "undeclared": ["instruments_etf.parquet"]}
```

Reported, not refused — declaring a subset is legitimate, a project may export every category its
exporter knows and trade only equities. What is not legitimate is doing it by accident. Matched by
the exporter's own `<stem>_<kind>.parquet` convention derived from the declared files, so a
hand-written roster under any other naming reports nothing rather than noise. Absent rather than
empty when there is nothing to report.

**An unsupported `kind` inside a table.** `export_roster` refuses one at export, so
`instruments.py` cannot produce it; it arrives exactly one way, from a parquet written or edited by
hand. That is a legitimate input — producing a clean table is the author's job and refusing a dirty
one is registration's — and `InstrumentKind` is closed, so it must not reach a run: a venue has no
terms for a category outside it.

It was already refused. What it did not say was *where*:

```
before: unknown instrument kind 'crypto'; declared kinds are etf, factor, index, stock
after : instrument 'BTCUSD' in the 'stock' table: unknown instrument kind 'crypto'; declared
        kinds are etf, factor, index, stock (declared tables: stock=instruments_stock.parquet)
```

For a three-thousand-row roster, locating the row is the entire cost, and the value alone does not
locate it. The `fix` now names `instruments.py` as the tool that cannot produce this input, which
is the shortest route back to a clean table for someone who edited one by hand.

## Validation

```
uv run pytest tests/ -q      # 1309 passed, 13 deselected
uv run ruff check src/vqapr/ tests/ showcases/   # 15 findings; the same 15 as 7ae3d3af, list
                                                 # compared entry by entry, none introduced
```

- `tests/cli/test_commands.py::test_a_run_says_whether_it_knew_what_its_instruments_were` — both
  states end to end through the CLI: a run with no roster reports `known: false` with a note naming
  the consequence *and* the remedy and freezes `roster: null`; the same spec after registering a
  roster reports the digest and per-category counts, and the frozen record carries the same,
  serialisable.
- `tests/test_instrument_roster.py::test_registration_names_a_table_sitting_beside_the_declaration_and_undeclared`
  — the undeclared file is named, and declaring both categories leaves the field absent.
- `tests/test_instrument_roster.py::test_an_unsupported_kind_in_a_hand_written_table_is_refused_by_instrument_and_file`
  — the instrument, the legal vocabulary, and the file are all in the refusal.
- `tests/cli/test_show.py` — the pinned `RECORD_FIELDS` set and the record fixture both updated to
  the new shape in the same change, which is what proves `show run` and the record still carry one
  field set.

The refusal-code baseline gains no code from this task: both registration refusals reuse existing
ones. Its drift against `7ae3d3af` remains the two codes record `068` added, with nothing removed.
