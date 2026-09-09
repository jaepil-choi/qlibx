# 150 — the run reports per strategy: a worker's refusal comes back, the refusal names its numbers and its strategy, and a live strategy can be watched

**Closes:** `docs/issues/archive/073`, `071`, `074`. **Branch:** `fix/073-the-run-reports-per-strategy`,
off `develop @ 3a814ed6`. **Authority:** the owner, 2026-09-04, on the recommendation to take
the three as one branch after scenario testbed run 4 (`kaist-thesis/vqapr-scenario-testbed/`,
`FINDINGS.md` F-005 to F-010) reproduced the paper end to end on the `0.4.0` wheel and lost two
ten-minute runs to the first of them. **Plan:**
`.agent/plans/completed/fix-073-the-run-reports-per-strategy.md`.

## Why this exists

Eight strategies, `vqapr run ff-arm --jobs 4`. At its 308th session one strategy returned a
`Rebalance` whose cash, after quantising seventeen short weights, was `2.000000000001` against a
`cash_upper` of `2`. Three things then went wrong in sequence, and each is one of the three
issues:

- The refusal said `cash_weight is outside the declared budget` -- no value, no bound, no
  strategy -- and its `source` was three nulls (`071`). The same envelope had reported an
  author's own `decimal.InvalidOperation` earlier in the run with no strategy id and no line.
- The `SimulationFailure` was raised in a worker and could not be pickled back to the parent:
  its constructor is keyword-only and it keeps the refused `Rebalance` (a `MappingProxyType`)
  on itself. The parent rendered `TypeError: cannot pickle 'mappingproxy' object`,
  `stage: unhandled`, `failures: []`, and named none of the seven strategies that had finished
  (`073`). In a single process the loop had stopped at the first exception and the strategies
  after it never started.
- For the ten minutes the run was alive, nothing on the surface said whether the strategy that
  had stopped writing parquet chunks at session 307 was dead or slow: `list` showed a record only
  once `strategy.json` was written, and the skill said "a long run can be watched" without
  saying how (`074`).

None of the three needed a design decision beyond one the issues had already posed -- whether
one strategy's refusal should stop the others -- so they were closed together and validated once.

## What changed

### A `Rebalance` refusal names its numbers (`071`)

`Rebalance.__post_init__`'s five `ValueError`s carry the value and the bound:
`cash_weight 2.000000000001 is outside the declared budget [-1, 2]`;
`target_weights are outside the declared budget bounds [-1, 1]: A=1.5, B=-1.5`; the sum refusal
shows the arithmetic; the empty-book refusal shows the cash. Offending weights are quoted up to
five and counted beyond that (`_offenders`), the way `Failure.examples` is bounded. The
dedicated long-only refusal stays but is unreachable through a valid `Budget`, which already
refuses a negative `target_lower` under long-only; the bounds check names the weight first.

### A `SimulationFailure` names its strategy and the author's line (`071`)

`SimulationFailure.__init__` takes `component_id` and `source` (both optional, so every
existing construction stands). `as_dict()` carries `component_id` at the top level and the
`source` in the synthesized entry; `str()` reads `simulation.callback.intent [never-ready]: ...`.
`FlowContext.failure()` fills them: `_component_id_of(layer)` reads `config.component` on a
strategy layer and `component` on a datamodel layer; `_author_frame()` walks the cause's
traceback and keeps the LAST frame whose file is the one the strategy class was loaded from
(`inspect.getsourcefile`), so a `Rebalance` refused inside `authoring.py` from line 67 of the
author's file points at line 67. `key_path` is `strategies.<id>` either way, so a framework
raise with no author frame still says which strategy it was about.

### A worker returns an outcome, and the run has one per strategy (`073`)

`orchestration.StrategyOutcome` (exported from `vqapr.public`): `component_id`, `status`
(`completed` | `failed`), `record`, `failure` (the `as_dict()` payload), `error` -- strings and
dict trees only, so it pickles. `run_registered_strategy` catches `SimulationFailure` and
returns a failed outcome instead of raising. `run()` collects an outcome for every strategy in
both branches: under `--jobs` from each future, sequentially by catching `SimulationFailure`
per strategy and continuing. `RunResult` gains `outcomes`, `errors` (the in-process exceptions),
`ok` and `failed`; `result(id)` raises the strategy's own `SimulationFailure` when it failed in
this process, and a `ValueError` naming the outcome when it failed in a worker. Non-simulation
exceptions -- `RunRecordExists`, `RunRecordLive`, `RunRecordConflict`, a bug -- propagate as
before: they are about the store or the package, not one strategy's decision.

`cli/run.py` builds the `strategies` map from the outcomes: a completed line is what it was plus
`status: completed`; a failed line is `status: failed` plus the whole failure payload (`stage`,
`family`, `component_id`, `failures`, `at`, `retry_precondition`). When any failed the envelope
is `_strategy_failed`: `ok: false`, `stage: run.strategy_failed`, `family` when the failed
strategies agree and `null` otherwise, `failures` gathering every failed strategy's entries each
stamped `strategy: <id>`, `error` saying `1 of 2 strategies failed: never-ready; the other 1
completed and their records stand`, and `run_id`, `store_root`, `strategies`, `roster` as on
the success path.

### A strategy still being written is listed (`074`)

`run_records.unfinished_strategy_refs` is the complement of `strategy_refs` (which still lists
finished records only). `strategy_progress` reads one directory: `status` (`running` while the
lock is inside `LOCK_STALE_AFTER`, `unfinished` otherwise), `lock` (`pid`, `refreshed_ago`),
`chunks` (the most parts any table has -- one per accepted session), `tables`, and
`last_event_time` (the max `event_time` of the newest part of any table, one small parquet read
per table). `cli/list_.py::_strategies` appends those rows after the finished ones, which now
say `status: completed`; `--strategy` and `--fingerprint` (against the `<fp8>`) apply,
`--since` reads `last_event_time`, `--failed-contract` never keeps an unfinished row.

The skill's stop condition names `status: completed`; two paragraphs follow it -- *When one
strategy fails, the others still run* (the envelope shape, the recovery loop with
`--strategy <id>`) and *Watching a long run* (the `list` row, what `unfinished` means); the
sentence at the table section points at them. `vqapr run --help` says every strategy is run,
what a refusal does to the envelope, and that `list strategies --run` shows progress.

## Decisions

- **One strategy's refusal does not stop the others.** Each strategy is its own flow with its
  own account (design section 7-4); a declined decision is that strategy's outcome. In a
  single process the loop continues; under `--jobs` the workers already did. This answers the
  question `071` posed. A `DATA`-family refusal that every strategy will meet costs a run of
  identical failures, one per strategy; `check` catches most of those before the run.
- **The worker returns an outcome rather than a picklable exception.** A `__reduce__` on
  `SimulationFailure` would have had to drop the owner objects and rebuild a different
  exception in the parent; an outcome that carries `as_dict()` is the same payload the
  single-process path renders and states the contract plainly.
- **No `not_started` status.** With the loop continuing there is nothing that does not start
  except when a non-simulation exception aborts the run, and then there is no envelope to put it
  in.
- **No `--progress` stream.** The `list` verb answers "is it stuck" with one command and no
  stdout contention (`047`); a stderr stream is a later decision if the verb proves not enough.
- **`unfinished`, not `killed` or `failed`, on disk.** A killed strategy and a refused one leave
  the same directory (rows, no record, lock released or stale). The listing does not guess; the
  run envelope is where a refusal is reported.

## Trade-offs

- `run()` no longer raises `SimulationFailure`. In-process callers that ran one strategy and
  used `RunResult.result()` still get the exception from `result()`; a caller that inspected
  `results` directly now finds the failed strategy absent and must read `outcomes`. No caller
  in the tree did the latter.
- The success envelope's per-strategy line gains `status`; `list strategies` rows gain
  `status`, and unfinished rows have `fingerprint: null` and no `period`.
- `SimulationFailure.__init__` grows two optional keyword parameters; the qa test's direct
  construction still works.

## Validation

- `uv run ruff check src/` clean.
- New tests: `tests/flow/test_a_run_reports_every_strategy.py` (single process; and under
  `--jobs 3`, marked `slow`), `tests/qa/test_a_budget_refusal_names_its_numbers.py`,
  `tests/cli/test_list_shows_a_strategy_still_being_written.py`, and
  `tests/cli/test_commands.py::test_a_run_names_every_strategy_it_ran_when_one_of_them_fails`.
- `PYTHONUTF8=1 uv run pytest tests/ -q -m ""`: see the plan's Validation section for the
  final count at the validated commit.
