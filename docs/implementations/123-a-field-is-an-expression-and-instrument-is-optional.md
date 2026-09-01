# 123 — A field is an expression, and instrument is optional

**Closes:** [`045`](../issues/045-a-requirement-cannot-say-which-rows-so-a-long-table-delivers-a-hundred-and-fifty-times-what-is-kept.md)
and [`038`](../issues/038-one-instrument-list-filters-every-requirement.md), implementing the owner
ruling recorded in
[`049`](../issues/049-following-the-packages-own-data-guidance-costs-six-hundred-times.md) — lane C
of the read-path campaign
([`2026-09-01-the-read-path-campaign.md`](../refactoring/2026-09-01-the-read-path-campaign.md) §2).
**Branch:** `read-038-049-fields-are-expressions`, rebased onto `develop@916554f2` — after lane B,
which is the merge order §3 fixes, and after records `124`/`125`.
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
| 4 | `DataRequirement` is `(dataset_id, field_id, lookback)` — see below | `data/requirements.py` |
| 5 | ~~field ids are unique per workspace~~ — **the ruling was wrong here, and the owner said so** | — |
| 6 | the schema is derived by `DESCRIBE <query>` and persisted; `show dataset` reports it | `data/scan.py`, `cli/show.py` |
| 7 | the workspace document migrates, write-forward, per entry | `workspace_codec.py` |

### Meeting lane B in `scan.py`

Lane B merged first and split the `RowsLookback` bound into a guess, a cold-start proof, and a
per-callback reuse — and made a bounded read carry its own proof forward, which is what took the
statement count from two to one. The same count therefore exists in **two** places: one `GROUP BY`
statement, and one window aggregate riding inside the read.

A grouped registration is exactly where those two can come apart, because a long source carries
several rows per instant and a `RowsLookback` counts instants. So the vocabulary is named once:
`_Counted` holds the relation, the two identity fragments and the counting arguments for one
registration's shape, and both the statement and the sidecar take it. There is no path left that
gives them different things to count.

**Making that mistake is loud on an all-aggregate registration, and that is not the guard.**
Forcing `_counted` to return the row-wise vocabulary for a grouped registration fails with
`Binder Error: aggregate function calls cannot be nested`, because counting the source through an
aggregate field is `count(sum(...))`. Checked by doing it. But a grouped registration may expose a
bare grouping key as a field — `{stamp: <the available_at column>, total: sum(x)}` binds grouped,
since the key is grouped by — and `count(<that column>)` binds fine while counting the wrong thing.
So the binder catches one shape of the mistake and not the other, which is precisely why the guard
is `_Counted` rather than duckdb. Lane B raised the risk and supplied that counterexample; both are
recorded in the test so nobody after us mistakes the binder for a safety net.

A dataset with no instrument axis takes no bound at all: the proof is per instrument, and there
are none.

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

### Item 5 was implemented, and then removed because it was wrong

The ruling's second point removed `dataset_id` from a requirement **because a field id is an id,
unique in the workspace**. That premise was implemented — registration refused an id another
dataset already exposed, naming that dataset — and then measured against
`vqapr-enhanced-index-3`, which is what this package is for. It does not hold there:

| | |
|---|---|
| datasets in that workspace | 27 |
| field ids exposed by more than one of them | **21** |

Two kinds, and the second is the one that settles it. `ff5-factors-broad` / `-k200` and
`residual-returns-broad` / `-k200` are **deliberately schema-identical parallel series** — same
component, same agenda, only the universe differs, and schema parity is what makes them comparable.
But `fiscal_yyyymm` is on six datasets simply because that is what the column is called wherever it
appears. Nobody chose a colliding name. A rule that makes that an error asks a researcher to invent
twenty-one names whose only purpose is to differ from each other.

Raised by `qlibx-b8`, verified here against the live workspace rather than taken from the report,
written into `049` with four options and none of them chosen, and decided by the owner:
**a requirement names `(dataset_id, field_id)`**. So `DataRequirement.of("statement-facts",
"net_income", lookback=...)`, no uniqueness refusal, and resolution asks only whether the named
dataset exposes the named field. `check` keeps both of its judgments, since an unregistered dataset
and an absent field are two repairs again.

**The `consumer_id` half of the ruling stands.** It is the half that was about who is reading, not
about what a name identifies, and nothing measured against it.

**One knock-on is undone with it.** While ids had to be unique the framework qualified the field
ids of published run records and allocations with their dataset id, because the five Flow-stamped
envelope columns and a default `weight` collide by construction. With ids unique only within a
dataset there is nothing to avoid, and those publications expose `weight` and `run_id` again.

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

**The baseline was measured, not quoted.** The campaign's §4 was amended while this lane was in
flight, after a fixed floor let a lane report green on three fewer passes; so the branch point was
detached and run here rather than taken from a document.

| gate | result |
|---|---|
| `uv run ruff check src/` | clean |
| `pytest tests/ -q -rs` at `develop@916554f2` | **1273 passed, 0 skipped, 14 deselected** — the baseline |
| `pytest tests/ -q -rs` on this branch | **1286 passed, 0 skipped, 14 deselected** |
| `pytest tests/ -q -m ""` | **1300 passed, 0 deselected** (9m 09s) |
| `pytest tests/ -q -m slow -rs` | **14 passed, 0 skipped, 1286 deselected** (6m 49s) |

Zero skips everywhere, which is the other half of that amendment: a skip is a test that did not
run, and `passed` alone does not show one leaking away. Both slow gates are run because record
`097` corrected that `-m ""` is the name of a call and does not prove what ran -- and here the two
numbers close on each other: 1286 + 14 = 1300, so the fourth gate names the fourteen the third one
merely included. The absolute numbers are far below earlier runs of this lane because the branch
point moved: records `124`/`125` deleted the layer the CLI could not reach.

All four were re-run on the tree that ships. An earlier pass straddled a one-line tidy in
`scan.py`, and a gate that ran against a tree nobody merges proves nothing about the one they do.

**One `-m ""` run went red and it was not this lane**, which is worth writing down rather than
re-running until it is green. `tests/test_workspace_concurrency.py::test_parallel_registrations_all_survive`
failed with `PermissionError: [Errno 13] ... .vqapr/.workspace.lock`. Record `044` already has this
test failing about 1 run in 10 on clean `0.1.0a10` and hardened the document **swap** with bounded
retries; this failure is on the **lock file** instead, which that fix did not cover. It was not
reproduced in 12 quiet runs on this branch, 8 on `develop`, or 15 on each under concurrent load —
and the test drives `Workspace.register_agenda`, while this lane's `workspace.py` diff contains zero
occurrences of `_exclusive`, `WORKSPACE_LOCK`, `register_agenda` or `os.replace`. Filed as its own
piece of work rather than absorbed here.

**+13, and every one is accounted for.** Eight are the acceptance file below — six for the ruling,
one for the seam with lane B, and one for the owner's correction. Three are
`tests/data/test_requirements.py`, where one test of the old signature's two rejections became four
of the new one's. The last two are not new tests at all:
`test_a_fix_is_not_its_requirement_restated`
parametrizes over every `Failure.bounded` call site, so this lane's net refusal change moves it —
`field_not_an_expression` and `projection_unbindable` added.

This worktree junctions `data/` from the main checkout, so the five `real_data` tests that skip on a
bare worktree actually run here — including the two that register Korean-named columns, which is
what proves a unicode identifier still binds inside a composed projection.

`ruff check tests/` reports findings that pre-exist at the branch point and are not in files this
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
- `test_two_datasets_may_expose_the_same_field_ids` — the corrected rule, on the campaign's own
  pair: the same eight field ids on two registrations is not an error, each requirement says which
  dataset it means, and provenance records which one answered
- `test_a_field_the_named_dataset_does_not_expose_is_refused` — the other half of the pair still
  has to be there, and the refusal names what the dataset does expose
- `test_a_registration_that_mixes_the_two_shapes_is_refused` — and that both binder lines reach the
  reader
- `test_a_field_expression_may_not_carry_its_own_from` — the property that makes a look-ahead
  unwritable rather than merely discouraged
- `test_a_bounded_grouped_read_returns_the_unbounded_answer` — the seam with lane B. A name whose
  two counts disagree (five produced values against ten source rows, against a declared eight),
  bounded read compared in full against the unbounded one

Lane B's own two, unchanged and passing: `test_a_declared_input_costs_one_statement_per_callback`
(3, 1, 1, 1, 1) and `test_a_proof_that_outlives_its_callback_still_returns_the_unbounded_result`.

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

**Three things block that measurement, and lane B hit all of them** — a drifted `probes.py`, 82
`+inf` rows that lane A's registration check now rightly refuses, and wall-time noise that reported
a 20% gain which was not there. They are written up where a measurer will look for them, in the
campaign document's §4, and are not restated here.
