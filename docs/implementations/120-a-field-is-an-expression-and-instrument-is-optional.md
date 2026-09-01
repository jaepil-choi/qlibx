# 120 — A field is an expression, and instrument is optional

**Closes:** [`045`](../issues/045-a-requirement-cannot-say-which-rows-so-a-long-table-delivers-a-hundred-and-fifty-times-what-is-kept.md)
and [`038`](../issues/038-one-instrument-list-filters-every-requirement.md), implementing the owner
ruling recorded in
[`049`](../issues/049-following-the-packages-own-data-guidance-costs-six-hundred-times.md) — lane C
of the read-path campaign
([`2026-09-01-the-read-path-campaign.md`](../refactoring/2026-09-01-the-read-path-campaign.md) §2).
**Branch:** `read-038-049-fields-are-expressions`, rebased onto `develop@111c0342` after lane A.
**Merges third**, and lane D opens on it.

## Why the two issues are one lane

`038` makes `instrument_field` optional and `045`/`049` make `fields` hold expressions. They land on
the same three points — `DatasetRegistration`, `declarations.py:414`, `workspace_codec.py` — and the
workspace document changes shape once for both. Split, the same code moves twice and the document
migrates twice.

## The ruling asserts two things that duckdb does not both allow

The composed query the ruling specifies is

```sql
SELECT <instrument_field> AS instrument, <available_at> AS available_at, <expr> AS <field-id>
FROM source GROUP BY 1, 2
```

and the same ruling promises that **every registration that exists today keeps working with no
edit**, because a bare column is the degenerate expression. Taken literally the two are not both
true. Measured against duckdb 1.5.5, which is the version this package pins:

```
SELECT ticker AS instrument, date AS available_at, close AS c FROM t GROUP BY 1,2
  -> Binder Error: column "close" must appear in the GROUP BY clause
     or must be part of an aggregate function.
```

**Wrapping bare columns in `any_value` buys the promise back and pays for it in silence.** A dataset
registered long today — `statement-facts`, keyed on six fields — would collapse from the 553,560
rows `045` measured to one row per instant, with no error anywhere. That is the first row of the
campaign's own risk table (§6): a green tree, a moved metric, and the wrong number.

### What was built instead: the binder decides, once, at registration

The identity columns are projected bare, which makes the two shapes mutually exclusive:

| shape | binds when | what the read path emits |
|---|---|---|
| **row-wise** | every field is row-wise | today's SQL, unchanged — `ORDER BY available_at, <key fields>`, one output row per source row |
| **grouped** | every field aggregates | `GROUP BY` on the identity columns, `ORDER BY available_at, instrument` |
| **mixed** | neither | refused at registration, carrying duckdb's own binder line |

No Python parses SQL to decide which. `scan.describe_projection` composes both shapes, asks
`DESCRIBE`, and takes the one that binds — the same call that types every field, which is why an
author never writes a type. The answer is stored beside the span, for the reason the span is stored:
it was measured, and **the read path validates nothing**.

This is not a widening of the ruling's grammar and does not touch what an author may write. It is
the only implementation under which both of the ruling's own claims hold.

## What changed

| # | what | where |
|---|---|---|
| 1 | `instrument_field` is `str \| None`; `.of()` defaults it to `None` | `data/datasets.py` |
| 2 | `fields` values are expressions; a bare column is the degenerate one | `data/datasets.py`, `declarations.py`, `project.py` |
| 3 | `observation_rows` composes from the settled shape; the window predicates stay the framework's | `data/scan.py` |
| 4 | `DataRequirement` is `(field_id, lookback)` | `data/requirements.py` |
| 5 | field ids are unique per workspace; a conflict is refused naming the other dataset | `workspace.py` |
| 6 | the schema is derived by `DESCRIBE <query>` and persisted; `show dataset` reports it | `data/scan.py`, `cli/show.py` |
| 7 | the workspace document migrates, write-forward, per entry | `workspace_codec.py` |

### The window is still written by the framework

`available_at <= evaluation_time`, the lookback bound and the instrument list are composed in
`observation_rows` and nowhere else. A field is an expression evaluated inside the window those
predicates draw, and the one expression form that could escape it — a scalar subquery, which brings
its own `FROM` — is refused at registration by `scan.statement_keyword`. That is a lexical check on
one token, not a parser: `extract(year FROM date)` and `sum(x) FILTER (WHERE ...)` are ordinary
expressions and keep working.

A `RowsLookback` ranks over whatever the shape produced — source rows when row-wise, one row per
instant when grouped. `_rows_lower_bound` takes the relation and its identity fragments from the
caller rather than deciding the shape a second time; counting a grouped registration's source rows
would exempt the wrong instruments, quietly.

### No instrument axis means no predicate and no column

A dataset registered without `instrument_field` gets neither the instrument predicate nor the
instrument column, its rows carry no `instrument` key, and the declared instrument list does not
narrow it. Its `AccessRecord` says so with an empty instrument tuple and no per-instrument counts,
rather than filing them under a name nobody chose. `ModelWindow.snapshot` returns its single row
unordered, because a table with no instrument axis has no cross-section to order.

### The consumer is stamped by whoever is running the component

`DataRequirement` carries no `consumer_id`, so the framework supplies it. A window built for one
component carries its id. The constraint window serves every loaded constraint at once, so it
carries **none and refuses to be read directly**: `project_constraints` and `evaluate_constraints`
take `window.for_consumer(constraint_id)` per constraint, sharing the one access log. Defaulting
instead of refusing would have made a wrong attribution the quiet outcome.

### Two collisions the framework had to answer for itself

Field ids are unique per workspace, and where the author chose the names that is a rule they can
satisfy. Two names are not theirs:

- the five Flow-stamped envelope columns are on **every** run record by construction;
- a published allocation's weight is named `weight` by default.

Both publication paths therefore qualify their exposed field ids with the dataset id. The parquet
columns are untouched; only the ids are, and a reader names `alpha_allocation_weight`.

### `check` loses a judgment because it lost its subject

`check.dataset.unregistered` was about a dataset a requirement named. Requirements no longer name
one, so `check.field.absent` answers what is left — a field nothing exposes, whether the dataset
behind it is unregistered or merely does not carry it. **Seven simulation judgments, not eight**,
and the count assertion in `tests/cli/test_check.py` says why rather than being loosened.

## The migration is a data-loss surface, and it is per entry

`_decode` validates forward references, so a workspace migrated forward and then reverted would fail
`Workspace.open()` on every command. Two independent axes now exist — the span (added when spans
became mandatory) and the derived field types (added here) — so **four document shapes decode**. An
entry written before either measurement decodes into exactly today's behaviour: bare columns,
row-wise, which is what those entries are. It is not repaired on read and not rewritten into the new
shape on the next unrelated registration; `_encoded_dataset` writes back the shape it read, exactly
as it already did for a span-less entry, so **the release that wrote a document keeps reading it**.

`_detach_registration` and `FrozenRun`'s copy both had to learn to carry the measurements. The
second is the one place in this change where a mistake would have been silent: `FrozenRun` copies
registrations positionally, and a grouped registration copied without `aggregated` reads row-wise,
returns ungrouped rows, and raises nothing.

## Gates

| gate | result |
|---|---|
| `uv run ruff check src/` | clean |
| `PYTHONUTF8=1 uv run pytest tests/ -q` | **1525 passed, 14 deselected** (baseline at the branch point after lane A: 1517) |
| `PYTHONUTF8=1 uv run pytest tests/ -q -m ""` | see below |
| `PYTHONUTF8=1 uv run pytest tests/ -q -m slow -rs` | see below |

The last two are both run because record `097` corrected that `-m ""` is a name of a call and does
not prove what ran.

This worktree junctions `data/` from the main checkout, so the five `real_data` tests that skip on a
bare worktree actually run here — including the two that register Korean-named columns, which is
what proves a unicode identifier still binds inside a composed projection.

`ruff check tests/` reports findings that pre-exist at `develop@111c0342` and are not in files this
lane touched; `src/` is the declared gate.

### The tests that close the lane

`tests/acceptance/test_a_field_is_an_expression.py` — the acceptance conditions, in the campaign's
own order:

- `test_criterion_1_a_long_registration_is_byte_identical_to_the_wide_one` — **this is the
  completion condition.** The same facts registered long, with the account pivot and the
  latest-dump tie-break written as field expressions, against the same facts pre-pivoted: eight
  published fields, full anti-join in both directions, zero rows either side. It includes the cell
  two download bundles disagree about — the decision a pivot cannot avoid — and an instrument that
  published no rows for a field, which must arrive as `NULL` rather than vanish
- `test_criterion_2_a_dataset_with_no_instrument_axis_is_not_narrowed` — `038`'s `kimchi-ff5` shape,
  with no factor id in `instruments:`
- `test_criterion_3_a_requirement_is_a_field_and_a_lookback` — the signature, and that
  `AccessRecord` still carries the consumer and the dataset
- `test_a_field_id_two_datasets_expose_is_refused_naming_the_other`
- `test_a_registration_that_mixes_the_two_shapes_is_refused` — and that both binder lines reach the
  reader
- `test_a_field_expression_may_not_carry_its_own_from` — the property that makes a look-ahead
  unwritable rather than merely discouraged

`tests/data/test_windows.py::test_rows_window_is_pit_bounded_and_counts_per_field` — a
`RowsLookback` still counts each field's own last N, now read one requirement at a time.

## What this lane did not do

- **Free SQL per field stays closed.** Expressions only. A field needing a join or a subquery is a
  DataModel, and opening it would lose the property in (1) of the ruling — a ruling change, not an
  implementation detail. No case was blocked while building this; if one appears it goes into `049`
  before the grammar moves.
- **`035`'s columnar accessor is not decided.** Re-measure after this merges, as §5 says.
- **No numeric baseline was regenerated.** `settle_contract_hml.fixture.json` and the showcase
  baselines are untouched.
- **`SKILL.md` still says nothing about the read cost of a long registration.** `049` calls that the
  cheapest thing on its list and it is not one of this lane's seven items. It is the first thing the
  campaign should pick up after lane D.

## The number this lane owes

Not measured here. The campaign's closing number — `annual-fundamentals`, 1,600 instruments × 4
evaluations, long registration, against the 806.61s baseline, with the anti-join run *before* the
timing — is reproduced against a built wheel in
`kwam-enhanced-index/vqapr-performance-testbed/`, and belongs to the campaign rather than to this
lane. What this lane establishes is the property that number would otherwise be meaningless without:
the two registrations deliver the same rows.
