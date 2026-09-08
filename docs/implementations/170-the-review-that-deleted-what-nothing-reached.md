# 170 — The review that deleted what nothing reached, and unified what was written twice

**Closes:** the ten findings of the 2026-09-08 code review (`/code-review high`, angles: DRY,
vulture dead code, reachability from the CLI and `vqapr.public`). **Branch:** `develop`, on top
of record `169`. **Owner decisions, 2026-09-08:** the sample moves under `tests/`; report fields
nobody reads are deleted; a method only tests call is presumed unneeded and is deleted once that
presumption is checked against the docs.

## Why

The review asked three questions of `src/vqapr` that the suite cannot: is the same logic
written twice, is anything unreached by every documented door, and does the configured vulture
gate still gate. It found three correctness defects hiding behind duplication, five hand-copied
implementations, a shipped subpackage and five shipped READMEs no door reached, twenty-odd
members only tests called, and a vulture report of 22 lines that the whitelist's own header
calls "a real finding" apiece.

## Correctness

- **`vqapr run <id> --strategy typo` rendered as `stage: unhandled`** (`cli/run.py`). Record
  `168` moved the judgments inside `preflight_run`, which put the member-selection loop first;
  its bare `KeyError` reached the envelope before any judgment refusal did. The lookup is now
  bounded as `cli.input.value_invalid`, naming the models the run does declare.
  Test: `tests/cli/test_run_makes_the_judgments_check_makes.py::test_an_unknown_strategy_name_…`.
- **A datamodel refused in a `--jobs` worker died as `stage: unhandled`, `failures: []`**
  (`flow/orchestration.py`). The strategy pool and the datamodel pool were copies; the
  `docs/issues/073` fix (a worker's failure must pickle) landed only in the strategy copy. Fixed at
  depth rather than by a second copy of the outcome trick: `VqaprError.__reduce__` rebuilds the
  error through its keyword-only constructor, so a datamodel's refusal crosses the `spawn`
  boundary as itself and the parent raises what the sequential loop raises; and one pool driver,
  `_in_workers`, now serves both kinds of run. Test:
  `tests/flow/test_a_datamodel_is_a_run.py::test_a_worker_refusal_comes_back_as_the_same_error_…`.
- **`public.register_component` wrote a component without conformance**, and the shipped sample
  used it for its exchange. `Workspace.Transaction.register_component` only persists;
  conformance lives in `extension/registration.prepare_component`, which the four `register_*`
  doors call. `public.component_ref` and `public.register_component` are deleted; every caller
  -- the sample, `tests/flow/test_valuation_clock.py`, and the eight showcases, which the
  review's reachability pass had missed because it read only `src/` and `tests/` -- goes
  through `register_strategy_model` / `register_exchange` / `register_constraint`, whose return
  value is the same `ComponentRef` the pair handed back. The skill never taught the pair (it
  teaches `vqapr register`), so no user-facing text changes. `registration.py`'s promise -- "a
  workspace never holds a reference to a component Flow could not call" -- is true of the
  Python door again, and the showcases now demonstrate the door that proves conformance.

## One implementation where there were several

- **`Failure.as_dict()`** (`domain/errors.py`) is the one spelling of the eight-key failure
  entry. `VqaprError.as_dict`, `InputError` (via a new `as_failure()`), `SimulationFailure` and
  `cli/check.py` delegate to it; `check.py`'s `_render`/`_from_input` are gone, together with the
  `spec`/`source` parameter that had been `None` since record `148` retired the spec file.
  `UsageError` keeps its own dict by decision: its `explain` is `None` (issue 030, record 114) and
  `Failure` requires a topic from the closed set; it now emits the keys in the same order.
- **`JUDGMENT_CODES`** (`flow/judgments.py`): one constant per judgment code, the tuple in
  judge order, and `JUDGMENT_BLOCKED`. `cli/check.py` derives `SIMULATION_CODES` and `CODES` from
  it instead of re-listing them; its list had drifted (`check.datamodel.output_registered` was
  missing) while `tests/cli/test_check.py` pinned `len == 8`. The test now compares the tuple to
  the `"check.…"` literals in the module source, so a tenth judge without a tuple entry fails.
  `run.check.judgment_blocked` stays out of `CODES`: `check` collects blocked judgments under
  `blocked` and never raises it.
- **`validate_requests`** and **`Fill.zero_dealt`** (`exchange/execution_table.py`,
  `exchange/fills.py`): the request-validation loop and the three zero-dealt branches that
  `AcademicExchange` and `KrxExchange` each carried, the third lift out of the two profiles after
  `requested_rows`/`accepted_requests` (issue 002). One check order (position before quantity)
  and one message set; the KRX "is not a whole share" text, wrong for a fractional rule, is
  replaced by the value, minimum and unit.
- **`analysis.signal.correlation`** is public and `report/measure.py` calls it. The report's own
  Decimal Pearson returned `0.999…97` for a series against itself (verified on a 50-point
  mixed-precision series and on the smallest real NAV path), which is why the correlation
  matrix's diagonal was forced to `1` by hand; the exact-Fraction implementation returns `1` and
  the special case is gone. Test: two identical return series correlate at exactly `1` off the
  diagonal.

## What nothing reached, deleted

- **`src/vqapr/agent/sample/` → `tests/sample/`.** No CLI command, `vqapr.public` name or
  `SKILL.md` path reached it; only `tests/conftest.py::sample_panel` and nine tests did. It was
  test code shipped in the wheel, the shape record `124` deleted. The facade-boundary count
  (`tests/boundaries/test_the_facade_is_not_reached_up_to.py`, `docs/design/agent-first-surface.md`)
  goes from 4 to 2: the two CLI verbs. PRD §11.4's "explicitly materializable" sample now has no
  user door; giving it one (`vqapr new --sample`, say) is a separate decision, recorded in
  `tests/sample/README.md`.
- **`src/vqapr/extension/templates/`**: five READMEs, no `.py`, no reader (`cli/new.py` inlines
  its templates), and instructions for flags that do not exist (`vqapr check .`,
  `vqapr register . --project`). Deleted.
- **Report fields nobody read** (`report/document.py`, `report/measure.py`): twelve fields no
  test asserted and no `SKILL.md` table asked for -- `annualized_mean_return`, the five `Book`
  means and `top_five_share`, `periods_positive`, `residual_pnl`, `positions_scored`,
  `median_periods`, `annualized_active_return`, `cumulative_active_return`. Kept, and now asserted
  on the fixture so they stop being unread: `intent.mean_gap` (Table 3), the headline's
  `cost_share_of_mean_nav_per_year` (Table 1's cost column), `Relative.tracking_error` (named in
  the skill's `relative` line).
- **Members only tests called**, each checked for a promised consumer before deletion:
  `RunStateRepository.accept_no_decision`/`accept_intent` and `capture_live_memory`/
  `restore_live_memory` (the loop composes `prepare_callback` + `publish` and calls
  `normalize_memory` itself; `tests/flow/test_acceptance.py` now asserts through that path),
  `RunRecordLive.holder` (a second spelling of `claim.pid`), `record.table_types`,
  `DuckDbObservationStore.query` (the hot-path cost guard now measures `query_many`, the path
  `data/windows.py` calls), `FrozenRun.physical_source_guarantee` (a test asserting a constant),
  `ExecutionHorizon.at_or_before` (the architecture doc's `_valuation_instant` paragraph
  described a chain that no longer exists and now describes `select_target`),
  `listings.rules_view` (told to authors, exported to nobody), `FillBatch.total_commission`/
  `total_tax`/`cost_by_kind` (the report computes the split from the fill table's `kind` column;
  record 072 already noted the method consumed no data), `OperationAgenda.from_occurrences`
  (`daily`'s docstring sent authors to a remedy no door reached; a wall time that does not exist
  or occurs twice is refused, and the docstring says so), and the unreachable second
  "both flags given" branch in `authoring_lookback.py`.
- **The vulture gate is green.** `uv run vulture` printed 22 lines; the whitelist header says
  each unlisted one is a finding. Three were misfires and are whitelisted with their callers
  named (`declared_digest`, read back by key from `run.json`; `strategy_configs`, the record-148
  retired section beside its record-144 siblings; the `__exit__` traceback argument is now
  `*_exc`, as `data/scan.py` spells it). Two were dead test helpers (`_Evidence` and its two
  carriers in `tests/acceptance/test_enhanced_index.py`; `_decision` and the `BUDGET` only it
  read in `tests/constraints/test_builtin.py`). The rest were the report fields above.

## Trade-offs

- `UsageError` is the one failure entry not rendered through `Failure`; the alternative was
  inventing an `ExplainTopic` for a skill section that does not exist.
- `tests/characterization/refusal_codes.baseline.json` gained two `unresolved` entries: the
  delegations in `inputs.py` and `evidence/artifacts.py` construct a `Failure` whose code is
  forwarded from an exception instance, which the static scanner cannot resolve. Keyed by line,
  so edits above them regenerate the baseline; teaching the scanner that a forwarded attribute
  is a re-render, not a declaration, is the cleaner fix and is left open.
- Report fields were judged by "does anything read it", not "could a paper want it". Two that
  feed a kept ratio (`annualized_active_return`, `positions_scored`) went too; the ratio's test
  recomputes them.
- The intermediate commits of this record were not each run through `test_all`; the tree at the
  last one was.

## Validation

All on the tree at the last commit of this record, 2026-09-08, alone on the machine:

- `uv run ruff check src/`: clean.
- `uv run vulture`: no output (22 lines before this record).
- `uv run pytest tests/ -q` (the iteration check): 1423 passed, 24 deselected, before the
  showcase rewrite; the two failures and four errors it showed were the showcases and one
  sample test still naming the deleted pair and the old `src/` path, fixed above.
- `test_all` (`uv run pytest tests/ -q -m ""`): **1453 passed in 431.6 s**, all eight showcases
  included; the slowest ten are the sample panel build (55.6 s setup, once), the warehouse
  fixture comparison (42.1 s) and the showcase block (23.7 s), the same shape record `169`
  measured. `show_003` reads the gitignored warehouse and was not run; its registration block
  changed the same way as the seven that were.
