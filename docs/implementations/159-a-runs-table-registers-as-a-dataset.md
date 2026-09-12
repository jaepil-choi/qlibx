# 159 — a run's table registers as a dataset: `flow/materialize.py` is gone

**Closes:** no issue. **Branch:** `step-04-delete-materialize`, off `develop @ 2d6719c0`.
**Campaign:** `docs/refactoring/2026-09-04-the-one-shape-campaign.md`, Step 4 (owner decision
D5). **Authority:** the owner, 2026-09-04, on the condition that the third path was confirmed
first — it was, in the campaign doc §1.4, and this record pins it with a test.

## Why this exists

`flow/materialize.py` (743 lines) existed to hand one strategy's output to another as a dataset:
`publish_run_allocation` took a finished run's in-process callback evidence, wrote a parquet under
`.vqapr/materialized/`, stamped a lineage file and registered the result; `publish_run_record` did
the same for any recorded table. Registration machinery, twice — the datamodel run has the same
three lines — and neither was needed after record `146` made a run's tables parquet: the
directory a run with a store streams `vqapr.weight` into **registers as-is**. One-shape D2: the
same rule in two places keeps one.

What the publication path *added* was a second clock (`availability_field`, per table) and a
lineage envelope. Both are answered elsewhere now: `available_at` is the row's `event_time`, the
decision instant it was written at (a valuation writes `observed_at` and `event_time` at the same
instant since `148`), and `run.json` carries the sha256 of every source a run read, which is the
provenance a later reader wants (`139`).

## What changed

- **Deleted:** `flow/materialize.py`, `flow/stamping.py` (its `derived_available_at` and
  `LookAheadDetected` now live in `flow/datamodel.py`, their one remaining caller — the docstring
  keeps the argument for why the look-ahead check is an invariant and not dead code),
  `tests/flow/test_publish_allocation.py`, `tests/flow/test_publish_run_record.py`,
  `tests/qa/test_run_record_availability_clocks.py` (the per-table clock it attacked is now the
  author's `available_at:` choice at registration, not a package rule to attack).
- **`public.py`:** six names gone — `AllocationPublicationSpec`/`Result`, `RunRecordSpec`/`Result`,
  `publish_run_allocation`, `publish_run_record`. `tests/boundaries/test_public.py` pins the new
  tuple.
- **Showcases 005–008:** each member run now takes `store_root=project / ".vqapr"`, and a local
  `_register_run_table(project, run_result, run_id=, component_id=, dataset_id=, table=, fields=)`
  registers `.vqapr/runs/<run>/strategies/<ref>/tables/<table>/` under the id the ensemble
  subscribes to, with `available_at="event_time"` and `weight` cast to `DECIMAL(38, 12)` (a record
  stores Decimals as text; the grid is `1e-12`, so the cast is exact). `_read_published` reads the
  directory and aliases `event_time AS available_at`, so every downstream reader in the showcases
  is untouched. Digests are over the directory's parts in name order; the lineage digests are gone.
  show_006's assertion 3 (which member carried state) now reads the run's final model state
  instead of the lineage's `state_path`.
- **Acceptance tests:** `test_enhanced_index` criterion 1/6 writes the accepted intent with
  `RunRecordWriter` and registers the directory; `test_ensemble_netting` criterion 11 likewise
  for `vqapr.account` (a hand-written record has no envelope, so it reads `account_version`
  rather than `run_id`); `test_signal_measurement` reads the directory the showcase's trace names.
- **New:** `tests/flow/test_a_runs_table_registers_as_a_dataset.py` — the campaign §1.4 experiment
  as a test: two sessions of `vqapr.weight`, registered, read back through `ModelWindow` as
  Decimals, and invisible before they happened.
- **`SKILL.md`:** *Registering a run's table as a dataset* — the YAML, where the ref comes from,
  why `event_time`, why the `CAST`.
- **Refusal-code baseline** regenerated: the `materialize.*` family is gone; nothing added.
- **`tests/flow/test_stamping.py`, `tests/qa/test_derived_available_at_boundary.py`** — repointed
  at `flow.datamodel`; they test the look-ahead check and keep doing so at its new home.
- **`data/scan.py::_relation`** — a directory source is read with `union_by_name=true`. This is
  the one package change the step forced, and the section below is why.

## The one thing this step found

**A run given a store keeps no rows in memory.** `RunState`'s row sink hands every chunk to the
record writer at publish and retains nothing on the roots, so `final_state.recorder_rows` is
empty for a stored run -- by design (`run_state.py`, "handed over at publish and never retained
by a root"). The showcases had only ever run members in-process, so every one of their readers
(`recorder_rows["signal.measurement"]`, the `vqapr.fill` replay, the default-table counts) assumed
the rows were there. Giving the member runs a store broke three of the four at once, and the fix
is the same fact read from the other side: `_recorded_rows(project, run_result, run_id=,
component_id=, table=)` reads the record directory back in commit order (`event_time, sequence`).
An in-process run (the ensembles, the index) is unchanged. A reader who gives a run a store and
then reaches for `recorder_rows` will hit this; the docstring on `recorder_rows` now says so.

**And the second thing, underneath the first.** Once the showcases read the record back, two of
them failed on `vqapr.account`: *"column `price` has type VARCHAR, but we are trying to read it as
type NULL"*. The record writer writes one part per session and types a column the first time it
sees a non-null value; a session whose only row is `_ACCOUNT` has `price` and `quantity` all-null,
so that part is written `null`-typed, and `_arrow_table`'s docstring states the contract: *"which
every reader unions with the later type."* The package's own reader did not. `scan.py::_relation`
built a plain `read_parquet('dir/**/*.parquet')`, which takes the schema from whichever part
duckdb opens first — so the same registered directory read or was refused **by part order**, and
`register_dataset` had passed on show_007 by luck. The fix is one clause on the directory branch
of `_relation` (`union_by_name=true`; a single-file source is untouched), and
`test_a_column_that_was_null_in_an_early_part_reads_with_its_later_type` pins the writer's stated
contract against the reader. Changing the writer instead (emit the declared type from the first
part) was the other option; it would have meant every reader of an *existing* record still
needed the union, so the reader is where the promise is kept.

## Measured

| | `b4bef34b` (Step 3) | after Step 4 |
|---|---|---|
| modules under `src/vqapr` | 127 | **125** |
| lines under `src/vqapr` | 31,461 | 31,647 |
| tests deleted / added | — | 3 files (−1,400 lines) / 1 file |

The source line count **rose** by 186 while 743 lines of `materialize.py` went: `datamodel.py`
took 60 for the folded stamping, the skill took 25, and the campaign counts `src/` only — the
four showcases each gained a 50-line helper that is the same helper four times. That is showcase
code, outside D2's scope, and it is the shape a user writes in YAML; a fifth copy would argue for
a public helper, and four is where it is noted rather than acted on.

## Validation

- `uv run ruff check src/` — clean. The showcases carry three pre-existing E501s (present at
  `HEAD` before this step); not touched.
- Targeted: `test_public`, the new test, `test_enhanced_index`, `test_ensemble_netting`,
  `test_a_datamodel_is_a_run`, `test_refusal_codes` — 46 passed.
- Showcase gate for 005–008 + `test_signal_measurement`: **8 passed** on the final run (005–008 through the gate, plus the four signal-measurement acceptance tests); each showcase runs its pipeline twice and compares directory digests across the replicates, so the registered tables are byte-deterministic.
- `uv run pytest tests/ -q -m ""` — **1419 passed** in 815s (fast + the thirteen slow journeys + all eight showcase gates), no flake this run. The count is 1,460 − 41 deleted tests (3 files) + 2 new − the rest folded.
- Process note: the first full run was **interrupted at collection** — two test files still
  imported `vqapr.flow.stamping`, missed by a grep that filtered on the module path rather than
  the import line. `--collect-only` before a full run would have caught it in one second; it
  is now the first thing to do after any module deletion.
