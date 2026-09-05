# 156 — refusals and summaries tell the truth: `079`, `083`, `084`, `085`

**Closes:** `docs/issues/079`, `083`, `084`, `085`; the `--kind` half of `082`. **Branch:**
`fix/refusals-and-summaries-tell-the-truth`, off `develop @ 6bfa85aa`. **Campaign:** none — four
message-and-payload defects from the 2026-09-04 real session, none in a file the one-shape
campaign's Steps 4–7 rewrite. **Authority:** the owner's rulings of 2026-09-05 (`079` option C;
`085` split the counter), plus two defects that needed no ruling (`083`, `084`).

## Why this exists

Four of the nine issues a real session filed at `0.4.1` share one shape: the code was right and
what it *said* was wrong or absent. `077` closed that shape in the judgment layer — a judgment that
could not look is not a judgment that passed — and these are its four recurrences in the message
layer. The rule is the same: state what is true, name what is registered, and assert no cause the
code did not measure. Grouped into one branch the way records `149` and `150` grouped their kin,
because each is small and they read as one correction.

## What changed

**`079` — `flow/datamodel.py::DataModelOutput.append`.** The `type_drift` refusal is gone. The
schema is whatever pyarrow inferred from the first non-empty session; when a later session's rows
do not fit it, the refusal is `datamodel.output.schema_mismatch`, its `observed` is pyarrow's own
sentence plus the established schema (`ratio: decimal128(28, 27)`), and its `fix` names the two
things an author can actually do — return `float` for a continuous quantity, or quantize a
`Decimal` to one scale in `compute`. It no longer says "return the same scalar type on every
session", which was already true in the run that filed the issue. The skill gains one bullet: what
`compute()` returns is typed by its first session, a `Decimal`'s scale is part of that type, and
the data and its types are the author's. Options A (a declared schema) and B (a refusal naming
precision as the cause) were declined by the owner.

**`083` — `cli/show.py::_model` and `cli/list_.py`.** A registered component of a kind the verb
does not describe (an exchange) is refused with the same `cli.input.value_invalid` an unregistered
id gets, naming the three kinds it does describe and the kind it got, instead of falling through
to the strategy loader's `TypeError` and leaving as `stage: unhandled` with an empty `failures`
list. `list components --kind <strategy|datamodel|constraint|exchange>` filters on the spelling
`list` itself reports, so the wrong ref is never assembled; `--kind` on any other `list` kind is
refused.

**`084` — `workspace.py::_merge_declaration` and `declarations.py::_apply`.** The run-conflict
refusal's `fix` names the third option it used to omit: `vqapr rm run-definition <id>`, then
register the edited declaration. The skill's *Correcting a registration during setup* paragraph
says a `runs:` declaration is the exception to replace-in-place and why. And `_apply` now parses
every run in a document before registering any, and refuses — `declaration.read.run_fed_by_sibling`
— a run whose `sessions_from` names a dataset that another run **in the same document** will
write, naming the producer and saying to split the document. The workspace refusal it pre-empts
could only say the dataset was unregistered.

**`085` — `analysis/execution.py::fill_summary`.** A new success-path field, `never_filled`: one
entry per instrument that was ordered in the run and never dealt once, with its order count and
its most frequent reason, most-ordered first. `reasons` is unchanged and still folds — that is what
it counts — but the axis it cannot see is beside it now. The optional `check` warning the ruling
allowed is **not** built: `check` has no advisory channel, adding one is a surface decision, and
the payload is what the issue asked for.

## Refusal-code inventory

Regenerated deliberately (`python -m refusal_codes` in `tests/characterization/`): one code
renamed (`datamodel.output.type_drift` → `datamodel.output.schema_mismatch`), one added
(`declaration.read.run_fed_by_sibling`). Nothing else moved.

## Validation

- `uv run ruff check src/` — clean.
- Targeted: the six touched test files plus the two new ones — 70 passed.
- `uv run pytest tests/ -q -m ""` — **1447 passed, 11764 warnings in 793.79s (0:13:13)** (fast + the thirteen slow journeys + the eight showcase gates).

New tests: `tests/flow/test_a_second_session_that_does_not_fit_the_schema_is_not_called_type_drift.py`
(the `079` reproduction: two ratios, two scales, the refusal quotes pyarrow and the schema and
does not say "same scalar type"); `tests/cli/test_a_run_fed_by_a_sibling_in_the_same_document_is_refused_by_name.py`
(`084`, two runs in one document, nothing registered); in
`test_show_model_reads_the_models_own_declarations.py` the wrong-kind refusal and `--kind` filter
(`083`); in `test_the_run_reports_what_its_orders_did.py` the reporter's 82-times-absent sleeve
beside one ordinary absence (`085`); and the `084` conflict test asserts the `fix` names the verb.
