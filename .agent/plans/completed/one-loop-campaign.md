# A market-clock instant costs less, and one loop walks both kinds of run

Status: complete

## Purpose

A minute-grained execution table makes the market clock tick 390 times a day, and every tick
costs about 100 µs per instrument -- 3,000 names is two minutes a day, eight hours a year, and
every mark batch stays in memory until the run ends. The owner's bar (2026-09-10): daily runs
blazing fast, minute runs fast enough, and clean architecture only where it does not cost
performance. This plan makes the tick cheap (P), then folds the two loops the two-clocks
campaign left side by side (L). Campaign document:
`docs/refactoring/2026-09-10-the-one-loop-campaign.md`.

## Scope and non-goals

In scope: `authoring/records.py`, `domain/shapes.py`, `flow/engine/run_state.py`,
`record/writer.py`, `record/schema.py`, `flow/run/*`, `flow/orchestration.py`, `flow/freeze.py`,
`authoring/{component,call,context}.py` (L5), tests and the hot-path guards.

Non-goals: a table-driven dispatcher; a journal for datamodel runs; package renames; changing
the position-row contract of `vqapr.account`; any change to a computed number (the showcase
digest holds).

## Acceptance criteria

- AC-1 `bench.py --names 3000 --days 1` run time falls from 117 s to under 40 s after P1-P4.
- AC-2 Retained `Mark` objects after a run are O(names), not O(instants x names) (P5).
- AC-3 Each P item has a count-based guard in `tests/flow/test_hot_path_costs.py`.
- AC-4 One loop class walks both kinds; `tests/flow/run/test_a_datamodel_is_a_run.py` green.
- AC-5 `Compliance.observe` takes one `ComplianceCall`; `test_a_role_has_one_call.py` green.
- AC-6 `test_all` green, showcase digest 83/83, ruff, pyright 0, `OPEN = {}` in the layers test.

## Repository context

Branch `redesign/one-loop` at develop `9ce50725`. The loop: `flow/engine/loop.py` (`EventLoop`),
`flow/run/loop.py` (`StrategyEventLoop`, `DataModelEventLoop`). The row path a market instant
takes: `flow/run/valuation.py::measurement_recorder` -> `authoring/records.py::InvocationRecorder`
-> `run_state.py::_staged/_stage_rows/_deliver` -> `record/writer.py::append` ->
`record/schema.py::_arrow_table`. The wiring table: `domain/wiring.py`. Reference branch for
records 203/205/207: `.claude/worktrees/redesign-four-kinds`.

## Milestones

- [x] M0: baseline. ruff clean, pyright 0, `tests/ -q` 1638 passed; benchmark moved to
  `experiments/exp_221_the_market_clock_cost/`; numbers in the campaign document §1.
- [x] P1: rows travel as columns (`RecordChunk`); recorder validates names once per spec;
  framework tables append columns; writer builds arrays from the remembered schema.
- [x] P3: the execution table is read ahead in windows of the market clock (record 222).
- [x] P4: framework-built views prove nothing twice; whitespace checks are one regex search (record 223).
- [x] P5: evidence keeps summaries; traces keep a root version, not the root (record 224).
- [x] L1: run-wide `sequence` (record 225); 207 was already develop's 212.
- [x] L2: a market instant is a fold over `MarketInstant`; five stages, one shape, five literal lines (record 226).
- [x] L3: `RunLoop` walks both kinds; `Part` (start/dispatch/finish) owns its receiver; `MarketClock.at` is the fold (record 227).
- [x] L4: `_run_member` runs both kinds inside one lifecycle; one window factory; shared facts blocks in freeze (record 228).
- [x] L5: `Compliance.observe(call)`; `test_a_role_has_one_call.py` (record 229).
- [x] Close: `test_all` 1692 passed; digest 81/81; ruff, pyright 0; release check recorded; campaign document §4; this plan moved here.

## Progress

- 2026-09-10 -- M0 done. Worktree synced, branch fast-forwarded to `9ce50725`. Benchmark:
  3,000 x 1 day 117.4 s; 300 x 1 day 15.7 s; 300 x 3 days 43.8 s; 300 x 1 day without position
  rows 8.7 s. Retained `Mark` = instants x names.

- 2026-09-10 -- P1 done (record 221). 3,000 x 1 day: 117.4 s -> 62.3 s; account_mark 68.4 -> 9.5 s. Guards in test_hot_path_costs.py.

- 2026-09-10 -- P3 done (record 222). 3,000 x 1 day: 62.3 s -> 45.7 s; snapshot 19.6 -> 3.9 s. First variant was slower (80 s): Arrow-to-Python cell conversion cost more than the queries it replaced.

- 2026-09-10 -- P4 done (record 223). 3,000 x 1 day: 45.7 s -> 32.7 s (min of two); compliance 15.7 -> 3.8 s. AC-1 (under 40 s) met.

- 2026-09-10 -- P5 done (record 224). Retained Mark 1,167,000 -> 3,000 (the account's one batch); traces no longer hold roots. AC-2 met.

- 2026-09-10 -- L1 done (record 225). Only the `sequence` column changed (46/46 tables equal to develop's otherwise); digest baseline re-recorded from this tree.

- 2026-09-10 -- L2 done (record 226). Stages are `(MarketInstant) -> MarketInstant`; compliance judges the mark VALUATION left rather than re-reading the root. Bench 34.7 s, digest 81/81.

- 2026-09-10 -- L3 done (record 227). AC-4 met. Bench 34.3 s (machine slower this session: build 2.5 s vs 1.0 s).

- 2026-09-10 -- L4 done (record 228). The rewrite first dropped develop's `record_ref=` on `RunOutput` (record 217): a diff of removed-vs-added lines caught it; the rule is in Decision log.

- 2026-09-10 -- L5 done (record 229). Skill edits need LF endings and a `_shipped.json` re-record (the release check and `tests/agent` pin both).
- 2026-09-10 -- Closed. `uv run pytest tests/ -q -m ""` 1692 passed, 4 skipped; digest 81/81 (show_003 hand-run); ruff clean; pyright 0; `record_shipped_skills.py --check` recorded. Branch `redesign/one-loop` at the closing commit, not merged.

## Discoveries

- `AcceptedRunState.recorder_manifests` is read by nothing outside `run_state.py` and grows by
  tuple concatenation on every publish: quadratic in publishes, invisible at 1,200 instants.
- `lifecycle_trace` is also tuple-concatenated per publish (O(instants) entries; left as is -- linear in instants, small per entry after P5).
- The per-instant retention was the traces holding each root (`OccurrenceTrace.state`), not the evidence alone; nothing read `trace.state`.
- `Compliance.observe(call, account)` is the one role whose authority sits beside its Call,
  while the wiring table lists `COMMITTED_ACCOUNT` as a View it receives.

## Decision log

- 2026-09-10 -- After rewriting a function wholesale, diff the removed lines against the added ones and read every line with no counterpart; a rewrite from memory of a file read before a fast-forward silently loses the fast-forward's changes.

- 2026-09-10 -- P before L: the benchmark puts the cost in the handlers' kernels and the row
  path, not in dispatch. Folding the loop first would move slow code and touch it twice.
- 2026-09-10 -- No table-driven dispatcher: five rows, one a placeholder; the market instant is
  a pipeline with typed hand-offs, which a table cannot express without hiding them.
- 2026-09-10 -- P2 (writer) folded into P1: the chunk shape decides both ends.

## Validation

- M0: `uv run ruff check src/` passed; `uv run pyright` 0 errors; `uv run pytest tests/ -q`
  1638 passed, 5 skipped.

## Risks and recovery

- The record's on-disk shape must not change (readers, `measure.py`, showcases). Guard: the
  showcase digest and `tests/record/*` read back what P1 writes.
- P3 changes which query produces a snapshot but not its rows; `test_stale_marks` and
  `test_valuation_clock` pin the selection rules.
- A milestone that fails its gate is reverted as one commit; the plan records why.

## Next action

None: the campaign is complete. Merging `redesign/one-loop` into develop, and the open item "position rows only on change" (campaign document §2, 하지 않는 것), are the owner's calls.

## Previous next actions

L5: `Compliance.observe(call)` with `call.account` (patch script `patch_l5.py` in the scratchpad); port `test_a_role_has_one_call.py` (written, in tests/boundaries); update skills, scaffold, docs; release note 0.11.0 §7. Previous:

L4: one member runner in `flow/orchestration.py` (`_run_member`: session, writer lifecycle, record read-back) with two assemblies; shared facts blocks in `flow/freeze.py`. Then L5. Previous:

L3: `RunLoop[TraceT, ResultT]` in `flow/run/loop.py` walks both kinds; `Part` protocol (start/dispatch/finish) for the strategy clock, `MarketClock.at` for the market clock; `StrategyEventLoop`/`DataModelEventLoop` keep their constructors and become assembly-only subclasses. AC-8 and the wiring test read `MarketClock.at`. Previous:

L2: `MarketInstant` fold in `flow/run/loop.py` -- one state object the five market-clock steps (accrue, fill, mark, observe, close) read and extend; the order stays one literal tuple; compliance receives `Marked` instead of rebuilding its evidence. Previous:

L1: port records 207 (`_next(**delta)`) and 205 (run-wide `sequence`) into `run_state.py`. Previous:

P5: evidence carries summaries, not mark batches -- `ValuationEvidence.marks`, `MarkEvidence.marks/selected_marks`, `ValuationResult.marks`, `FeedbackEvidence.candidates`, `AccountCommitEvidence.execution_snapshot` (rows) -> `MarkSummary` / `SnapshotSummary`; retained `Mark` objects must drop from instants x names to O(names). Previous:

P4: framework-built `EconomicAccountView` and `ModelWindow` skip re-validating instrument ids the frozen run already validated (`build_account_view` -> `_copy_weights` 9.8 s; `ModelWindow.__init__` 4.5 s). Previous:

P3: one execution-table read per trading day serves every instant's snapshot (a cursor shared by `ExecutionHandler.fill` and `ValuationHandler.mark_held`); then P4. Previous:

P1: add `RecordChunk` to `domain/shapes.py`; rewrite `InvocationRecorder` staging as columns;
thread the chunk through `run_state.py` (`sink`, `new_chunks`, `_recorder_chunks`) and
`RunRecordWriter.append_chunk`; `measurement_recorder` uses `append_columns`; update the three
tests that pass `row_sink=writer.append`; add the two count guards; run the benchmark.
