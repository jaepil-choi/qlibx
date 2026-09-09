# 149 — the issues left open at 0.4.0, closed on one branch

**Closes:** `docs/issues/archive/055`, `056`, `057`, `060`, `062`, `063`, `066`, `067`, `068`, `069`,
`070`; the docs half of `065`. **Branch:** `fix/0.4.0-open-issues`. **Authority:** the owner,
2026-09-04 — *"1번 덩어리를 한 브랜치로 모두 닫고, 같은 브랜치에서 코드 부분도 수정하고 넘어가자"*,
after ruling `064` closed won't-fix (same-close trading is look-ahead; the one-session lag is
the framework's intent) and `070` a defect (*"run이 workspace.yaml을 4번이나 여는것은 문제야"*).

## Why this exists

`v0.4.0` shipped the deletion campaign with fourteen issue files open. Eleven were found by the
scenario testbed's first user agent on the `0.3.0` wheel (`055`–`068`) and two by the 0.4.0 spine
trace (`069`, `070`). Six were sentences in the shipped skill that the code no longer backed, or a
message that was correct and not enough to act on; five were code. None needed a design decision,
so they were closed together and validated once.

## What changed

### The skill follows the code (`062`, `067`, docs half of `065`)

- `Hold(reason=...)` takes prose; the skill said "one token, no spaces" while the docstring and
  the validation accepted spaces (record `125`). The skill states the docstring's rule and the
  scaffold's example reason has spaces, so the example is the documentation.
- The skill promised `vqapr register <file> --force` for an edited component and said a plain
  re-register was refused; the CLI had no such flag and replaced in place silently. The skill
  now says the edit loop is the same `register` command again and that no `--force` exists;
  `Workspace.register_component` lost the `force` parameter that gated nothing; `register <kind>
  <id> <file>` answers `replaced: {fingerprint: <old>}` when an id changed hands. The skill's
  `vqapr remove` became `vqapr rm`, the verb that exists.
- `Model.inputs`'s docstring and the skill say `inputs()` is evaluated at registration and
  preflight before any memory is applied. Whether one class may be registered under several ids
  with a config is still the owner's question (`065`, design half, open).

### The scaffold names the read it was asked for (`063`)

`vqapr new strategy ou --dataset residuals --field resid` emitted `{"prices": read}` and a
docstring describing a momentum ranker. The alias is the dataset id in both the strategy and the
datamodel template (`{"residuals": read}`, `call.read("residuals", "resid")`), the history blocks
are formatted with it, and the class docstring names the dataset and the field and calls the
example signal a placeholder. The strategy scaffold stays within its forty-line ceiling
(`tests/extension/test_authoring_contract.py`).

### One missing dataset is one failure (`056`)

`_judge_datasets_and_fields` collects the unregistered dataset ids across a component's
requirements and emits one `check.dataset.unregistered` per dataset, the fields it wanted riding
as `examples`. Seven fields from one missing dataset were seven identical failures.

### A missing record is refused by name (`057`)

`run_records._resolve_ref` sits under `_parts` and `table_ids`: a root without the run directory
is refused with `RunRecordMissing` (a `ValueError`) naming the `runs/` directory it looked in and
the run directories present -- finished or not -- and saying the root is the `store_root` `vqapr
run` prints, not the project directory; a `strategy_ref` naming no directory is refused listing
the refs present; the bare `<strategy-id>` resolves the way `vqapr show strategy` does; `None`
reads the run directory when it holds tables of its own (a pre-`139` record, a writer without a
member) and otherwise resolves to the run's only strategy, refusing when there are several. A
declared-but-unwritten table still reads back empty. `RunRecordMissing` is exported from
`vqapr.public`; `--store-root`'s help and the skill say what the root is.

### Every envelope names its workspace (`066`)

`cli/main.py` stamps `workspace_root` (absolute) on every payload, success and failure.
`--project-root` defaults to `None`; an implicit root that holds no workspace while an ancestor
does is refused before any handler runs, naming both directories and the two ways forward
(`--project-root <ancestor>` or `--project-root <here>` on purpose). An explicit root is never
second-guessed. `Workspace.create` is unchanged: the discovery rule belongs where the default is
chosen.

### `show model` reads the model (`055`)

`cli/show.py::_model` builds `reads` from `inputs()`, `forms` and `records` from `tables()` and
`account_history()`, and `decides` as the distinct dataset ids in declaration order. The three
private attributes it read (`_aliases`, `_authored_tables`, `_authored_history`) were relics of
the shape records `126`–`133` removed; nothing assigned them and `getattr` defaults hid it.

### `vqapr rm dataset <id>` (`060`)

`Workspace.remove("dataset", id)` withdraws the registration and, when no other dataset names
the same source, the source with it. `_references_in` names the registered runs whose
`sessions_from` is that dataset as blockers; a component's reads are in its code and are refused
at its next preflight; a datamodel run that WRITES the dataset is not a blocker, because
withdrawing the output is how that run is run again. The CLI deletes
`.vqapr/materialized/<id>/` when the dataset's source lives there and leaves a user's own path
alone; the payload says `deleted: <path>` when it did.

### The agenda is cut on dates, built once per command (`069`)

`derived_agenda` drops sessions whose venue-local date lies outside `[start, end]` before
`OperationAgenda.daily` builds an occurrence -- a superset of what `inclusive_slice` keeps, so
nothing it answered changes -- and `judgments()` derives the agenda once and hands it to
`_judge_execution_ordering` and `_judge_datasets_and_fields` (`_first_decision` takes it too),
where it was derived per strategy and per member. A strategy's identity folds the sliced
occurrences (`FrozenAgenda.encoded()`), so no record moves; the recorded `content_identity` is now
the sliced agenda's.

### One workspace per `run` command (`070`)

`cli/run.py` opens the document once and hands it to `preflight_run` (which now takes a
`Workspace` or a root) and to `run` (`workspace=`). `run` reads the roster once, through that
workspace, and passes it to every `_run_strategy`; `RunResult.roster` carries it to the envelope,
which no longer re-reads it, so the `stale` branch that described a re-read failing after the run
is gone. `registered_roster` accepts a `Workspace`. A `--jobs` worker still opens its own, by
design.

### The snapshot is columnar and the run says where its time went (`068`)

`scan.exact_snapshot_rows` fetches with `fetch_arrow_table()` and builds the same dict rows from
columns: `trade_at` converts once per column rather than once per cell through `pytz`.
`FlowContext.timed(phase, operation)` accumulates seconds; `due_boundary` times every due stage
by its `SimulationStage` name, `SimulationFlow` times `callback` and `due`, and `run()` adds
`total`. `SimulationResult.timing` reaches the strategy record as `timing` (a new
`_STRATEGY_FIELDS` entry) and the run envelope's per-strategy line. The issue's second bullet --
one snapshot per session -- was already record `148`'s.

## Trade-offs

- `workspace_root` is a new key on every envelope. A test comparing the datamodel envelope's
  keys to the record's now excludes it, as it excludes `ok` and `stage`.
- Refusing an implicit root beneath a workspace changes what `vqapr new constraint x` does in a
  subdirectory of a project: it now refuses instead of starting a workspace there. The refusal
  names the explicit spelling that does what the user may have meant.
- `derived_agenda` returns fewer occurrences than the dataset has sessions; three preflight tests
  that inspected `daily` through it now widen the period to cover the days they list.
- `RunResult` and `SimulationResult` grow a defaulted field each; every existing constructor call
  keeps working.

## Validation

- `uv run ruff check src/` — clean at every commit.
- Targeted suites per milestone, green.
- `PYTHONUTF8=1 uv run pytest tests/ -q -m ""` — **1398 passed** at dca52121 (702 s). The run
  before it, at 42146d1c, had six failures: five tests that pinned the contracts this branch
  changed (the deferred-import ceiling, `_roster_envelope`'s argument and its `stale` branch,
  the strategy record's field set), updated in dca52121, and one load-induced flake in
  `tests/qa/test_run_records_survive_and_race.py` that passes alone and in the final run.
- New tests: `tests/cli/test_the_skill_matches_the_code_it_ships_with.py`,
  `tests/extension/test_the_scaffold_names_its_alias_after_the_dataset.py`,
  `tests/flow/test_a_missing_record_is_refused_by_name.py`,
  `tests/cli/test_a_refusal_names_the_workspace_it_looked_in.py`,
  `tests/cli/test_show_model_reads_the_models_own_declarations.py`,
  `tests/cli/test_rm_dataset_withdraws_a_registration.py`, and one test each in
  `tests/cli/test_check.py` (`056`), `tests/flow/test_preflight.py` (`069`) and
  `tests/cli/test_commands.py` (`070`, `068`).
