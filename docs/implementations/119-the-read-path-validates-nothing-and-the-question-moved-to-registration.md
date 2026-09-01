# 119 — The read path validates nothing, and the question moved to registration

**Closes:** [`044`](../issues/044-the-read-path-revalidates-eight-column-names-once-per-row.md) —
lane A of the read-path campaign
([`2026-09-01-the-read-path-campaign.md`](../refactoring/2026-09-01-the-read-path-campaign.md) §2),
applying the owner ruling recorded in
[`049`](../issues/049-following-the-packages-own-data-guidance-costs-six-hundred-times.md).
**Branch:** `read-044-no-validation-on-read`. **Merges first**, before lanes B, C and D.

## Why this change exists

`DuckDbObservationStore.query` handed every row it had just read out of its own registered parquet
to `normalize_rows`, which asked each cell whether it was a portable finite scalar and asked each of
the eight column names, **once per row**, whether it contained whitespace. `044` measured the second
question as the larger half; `035` had measured the pass as a whole at 1.635s of a 3.498s accessor.

Neither question could learn anything. The rows come out of `scan.observation_rows` three statements
earlier, built from one cursor description, so every row in a batch carries the *identical* `names`
tuple — the same `str` objects. And the values are the file's own, in columns a registration
accepted.

**The owner ruling: the read path validates nothing.** What a registration accepted is thereafter
trusted, and data that only turns out to be wrong at runtime is not chased — it blows up where it
happens and the message is passed through unedited.

## The thing this record exists to be judged on: it is a move, not a deletion

`035`'s addendum named this lane's failure mode before the lane existed. `normalize_scalar` was, at
the time it was written, the only thing standing between a NaN in a registered column and a model
consuming it. **Removing the read-path pass without relocating the check trades 1.6s per evaluation
for a silent NaN**, which is the class of failure this package exists to refuse — a NaN does not
fail where it lands, it propagates through every number it touches and the run still reports a
result.

So the pass was not deleted. It was moved to registration, where the same question is answered
**once per column** instead of once per cell, against a file that is about to be read thousands of
times.

### Three questions moved, not one

`normalize_scalar` refused three distinct things, and relocating only the finiteness check would
have reproduced the addendum's trade against the other two. All three now have a home in
registration:

| what `normalize_scalar` refused | where it is answered now | cost |
|---|---|---|
| a non-finite float | `datasets.check_values` (stage 4), via `scan.finite_check` | one scan, and only when a numeric column is exposed |
| a naive datetime | `datasets.check_schema`, `dataset.register.schema.field_not_tz` | free — the schema already says it |
| a non-portable type | `datasets.check_schema`, `dataset.register.schema.field_not_portable` | free — the schema already says it |

The two schema-stage legs are the reason validation got *earlier* rather than merely cheaper: a
column that is a naive timestamp, or a `STRUCT`, is that for **every** row, so asking the file was
always the wrong instrument. Both refusals land before any full scan runs
(`timing.key_was_skipped is True`, asserted).

`available_at` was already checked for tz-awareness; that is unchanged. What is new is that the
**exposed `fields:` columns** are held to the same standard, because those are the ones the read
path hands to a model.

## What changed

| file | change |
|---|---|
| `src/vqapr/data/store.py:93` | `normalize_rows(raw_rows)` removed. The rows go to `ObservationBatch._trusted` as they came back from `scan.observation_rows`. The comment there now states the ruling rather than the old "already normalized" argument |
| `src/vqapr/data/scan.py` | **added** `FiniteCheck` and `finite_check`. One aggregate per column in **one statement**, so a wide declaration does not read the file once per column — `048` is precisely the finding that registration cost follows declaration width, and this is the place that mistake would have been repeated. Examples are fetched only when a column violates, the same shape `key_check` uses |
| `src/vqapr/data/datasets.py` | **added** `VALUE_STAGE` and `check_values` (stage 4). `check_schema` gained the two zero-I/O legs above and its docstring now says what it is for |
| `src/vqapr/agent/skill/SKILL.md` | registration is repriced. It now says the extra pass exists, that it is one pass however many numeric fields are declared, and — the part an author needs — that **a non-finite value is refused here or nowhere**, so an absent value belongs as `NULL` |
| `tests/characterization/refusal_codes.baseline.json` | regenerated. **4 codes added, 0 removed, 0 renamed**; the rest of the diff is line drift from the inserted blocks. The additive-only shape is the evidence that nothing existing was displaced |

`normalize_rows` itself is untouched and still used by all three callers that take outside input:
`ObservationBatch`'s public constructor, `EvidenceRecorder`, and `_validated_output` for what a
`DataModel.compute` returns. Those are boundaries where keys legitimately differ per row, which is
the caller the per-row key check was correct for all along.

**`scan.py` contact was kept to one added function and no edit to an existing one.** That is the
reason this lane merges first: lanes B, C and D all rewrite `observation_rows`, and this lane does
not touch it.

## Measured, and one claim corrected

Synthetic source of the shape `044` reports — 100 instruments x 5,536 sessions = 553,600 rows x 8
columns, one evaluation, warm session, no profiler. Three samples, medians below.

| pass | seconds |
|---|---|
| `scan.observation_rows` — SQL, `fetchall`, one dict per row | 4.520 |
| `normalize_rows` | 3.767 |
| the same, key check hoisted out of the row loop | 1.345 |
| the per-row non-null counting in `query` | 0.357 |

| read path | seconds |
|---|---|
| **before** — scan + `normalize_rows` + counting | **8.644** |
| **after** — scan + counting | **4.877** |
| | **−43.6%** |

**The correction.** `044` claims the key check is "roughly three quarters" of `normalize_rows`. It
is not, at this shape: across three samples the hoisted variant lands at 63%, 66% and 71% of the
pass, median **64%** — closer to two thirds than to three quarters. The direction is confirmed and
the ordering `044` set out to fix is confirmed (the key check is the larger half, against `035`'s
assumption), but the magnitude is overstated by roughly a tenth of the pass.

Two honest caveats on that number, because it is the one thing this record was asked to falsify:

1. The hoisted variant rebuilds each row with a dict comprehension where `normalize_rows` uses an
   explicit loop, so the comparison is not a perfectly isolated measurement of the key check alone.
2. It is moot for the shipped change. `044` measured the split because shapes 1 and 2 of its "what
   to settle" section keep the value check; under the ruling **the whole pass goes**, so what is
   removed is 3.767s, not the 2.4s the key check accounts for.

Registration pays for it. On the fixtures the added scan is not separable from noise; the honest
statement of its cost is structural rather than numeric: **one extra full aggregate over the source,
skipped entirely when no exposed field is numeric**, asserted by a test that fails if the scan runs.

## What was deliberately not done

- **The per-row `isinstance(available_at, datetime)` in `store.query` stays.** Under the ruling it is
  also read-path validation the schema stage already guarantees, and removing it would let the
  comparison below it raise on its own — which is what the ruling asks for. It is left in place
  because it is not what `044` measured (it lives inside the 0.357s counting pass, not the 3.767s
  one) and because this lane's narrow contact surface is why it merges first. **Flagged here so it
  is a decision rather than an oversight.**
- **No columnar accessor.** Campaign §5 defers it until after lane C, on the ground that the thing
  it would be measured against changes from 4,428,480 cells to 3,375.
- **The row-order contract is untouched** — `available_at`, then the dataset's key fields. It is
  promised in `SKILL.md` and cross-sectional models depend on it.

## Validation

| gate | result |
|---|---|
| `uv run ruff check src/` | clean |
| `PYTHONUTF8=1 uv run pytest tests/ -q` | **1510 passed, 5 skipped, 14 deselected** (baseline at the branch point: 1492 passed, 5 skipped). The 5 skips are the `real_data` tests; this worktree has no `data/vqapr-dev/price_daily` |

The count moves by 18 for 14 new test functions. The other four are not new tests: they are
`test_a_fix_is_not_its_requirement_restated`, which parametrizes over every `Failure.bounded` call
site in the tree. The four refusals added here were held to that standard without being asked to
be -- a `fix` may not restate its own `requirement`.

`ruff check tests/` reports 9 findings, all pre-existing at `develop@50bc1a48` and none in a file
this lane touched; `src/` is the declared gate. `ruff format --check` is likewise not a gate here —
two `src/` files fail it at HEAD, verified against `git show HEAD:`.

### The tests that close the lane

`tests/data/test_datasets.py` — the acceptance condition is the first of these:

- `test_a_nan_column_is_refused_at_registration` — **this is the completion condition.** It fails on
  a tree where the pass was removed without being moved
- `test_the_refusal_names_the_field_and_counts_what_it_found` — a refusal that says only "there is a
  NaN somewhere" sends the author back through the whole file
- `test_a_null_is_not_a_non_finite_value` — `NULL` is a missing observation, not a wrong number.
  Counting it as a violation would refuse every sparse panel
- `test_a_naive_timestamp_field_is_refused_before_any_scan` and
  `test_a_field_that_is_not_a_scalar_is_refused_before_any_scan` — the other two legs, and that they
  cost no I/O
- `test_only_the_exposed_columns_are_checked` — registration judges the declaration, not the file.
  The fixture carries a NaN, a naive timestamp and a `STRUCT` at once; a registration that exposes
  none of them passes
- `test_a_declaration_with_no_numeric_field_does_not_open_the_file_for_it` — `048`'s mistake, made
  falsifiable: the test fails if the scan runs

`tests/data/test_scan.py` — `finite_check` directly: per-column counts from one pass, examples that
carry the instrument and the instant, a null-only column passing, and an empty column list refused.

`tests/data/test_the_read_path_validates_nothing.py` — the ruling as behaviour:

- `test_the_rows_are_exactly_what_the_removed_pass_would_have_produced` —
  `rows == normalize_rows(rows)`. The removed pass validated and passed values through untouched; if
  that equivalence ever breaks, the removal changed the contract
- `test_the_row_order_contract_survives_the_removal`
- `test_a_nan_that_appeared_after_registration_is_delivered_rather_than_refused` — the ruling stated
  so that it is falsifiable. It fails on the pre-change tree, where `normalize_scalar` raises. **The
  day this test flips is the day validation came back to the read path**, and what comes back with
  it is the cost `044` measured
