# 157 — enumerate, then cascade: `080` and `081`

**Closes:** `docs/issues/080`, `081`. **Branch:** `fix/080-081-enumerate-then-cascade`, off
`develop @ a244260e`. **Campaign:** none — these touch `flow/run_records.py` and `cli/rm.py`,
which one-shape campaign Step 6 will reshape; done first, as small additions, because the owner
ruled deletion must be easy and the cascade cannot stand on an enumeration that misses what a
crash leaves behind. **Authority:** the owner, 2026-09-05 (`081`: build the cascade; `080` is its
prerequisite).

## Why this exists

Two findings from the 2026-09-04 real session, one shape: **readable but not findable.**

`080`: a datamodel run that died inside a callback left `<id>@<fp8>/tables/` and no
`datamodel.json`. `list datamodels --run` read finished records only, `rm datamodel` resolved a
member through the finished set, and the skill sold the directory count as the tuning history —
so the crashed directory was invisible, unnameable, and counted as a tuning. The strategy side
had all three answers since record `150`.

`081`: `rm run-definition` withdrew a definition and `list runs` — which walked the registrations
— stopped showing the id, while 18,067 rows of record sat readable underneath. The last cleanup
step, `rm run <id>`, then needed an id the surface no longer printed. Removing one discarded alpha
took five commands in an order nothing stated.

The ruling that shaped the fix: a cascade built on an enumeration that cannot see the crashed
directories would delete what it can see and report success — `080` amplified into a command that
claims completeness. So `080` lands first, in the same branch, and the cascade reads through it.

## What changed

**`flow/run_records.py`.** `unfinished_strategy_refs` and `strategy_progress` become thin
wrappers over kind-generic `unfinished_member_refs(kind=)` and `member_progress(kind=)`, and the
datamodel side gets `unfinished_datamodel_refs` and `datamodel_progress` — the same three states
(`completed`/`running`/`unfinished`), the same `chunks`/`tables`/`last_event_time`/`lock`. New
`recorded_run_ids(root)`: every run the store holds any trace of — a run record, or a member
directory of either kind — which is the wider set `list runs` needs.

**`cli/list_.py`.** `list datamodels --run` gains the unfinished pass `list strategies` has, each
row carrying `status`. `list runs` reports a `status: registered` row per definition and a
`status: orphaned` row (`definition: null`, `recorded`, `unfinished`) per run the store holds
that the workspace no longer registers.

**`cli/show.py::resolve_member(unfinished=)`.** Widens the known set to record-less directories.
`show` keeps reading finished records; `rm strategy` and `rm datamodel` pass `unfinished=True`,
because a directory a crash left is precisely the one a reader wants to remove.

**`cli/rm.py`.** Three things. `rm run-definition` reports `records_remaining` and, when any,
`remove_records_with: vqapr rm run <id>`. `rm run` resolves through `recorded_run_ids`. And
**`rm run <id> --cascade`**: records first (the only step that can refuse, on a live lock, and
`remove_run_record` checks every lock before removing anything), then the definition, then the
materialized outputs its datamodels wrote, then the components it named — keeping, and reporting
as `kept` with `held_by`, any dataset or component another registered run still names. A failure
after records are gone is not rolled back: deleted evidence cannot be restored, so the payload says
what went and what remains. `--cascade` on any other kind is refused.

**`SKILL.md`.** *Tweaks are records, not directories* — count `status: completed` rows, a crash is
`unfinished`, `rm` names it — and a paragraph for `rm run --cascade`, the orphan row and the
`rm run-definition` payload.

## What did not change

The single-kind verbs keep their meaning: `rm run` still removes records only, `rm run-definition`
still withdraws only. The module docstring's argument that a registration and a record are
different things stands; the cascade is one explicit gesture that says *remove all of it*, not a
change to what the other verbs do. `Workspace.remove` and `_references_in` are untouched — the
cascade asks them and reports their refusals as `kept`.

## Validation

- `uv run ruff check src/` — clean.
- Targeted: `test_rm_dataset_withdraws_a_registration`, `test_list_shows_a_strategy_still_being_written`,
  `test_a_datamodel_run_through_the_cli`, `test_run_records`, `test_commands`,
  `test_refusal_codes` — 53 passed; the two new files — 6 passed.
- `uv run pytest tests/ -q -m ""` — **1452 passed, 1 failed** in 817s (fast + the thirteen slow
  journeys + the eight showcase gates). The one failure is the race flake described below,
  and nothing else; re-run in isolation immediately after: 5 of 6.
- `tests/qa/test_run_records_survive_and_race.py::test_five_processes_racing_...` flaked at its
  documented rate in isolation on this branch (1 of 6, documented ~1 in 12) after a burst of 3 of
  5 immediately following the source edits, when all five children byte-compiled the changed
  modules at startup; 5 of 5 on `develop` under the same conditions minutes later. The diff to
  `run_records.py` is a pure refactor that does not reach `_open`.

New tests: `tests/cli/test_list_shows_a_datamodel_still_being_written_and_rm_can_name_it.py`
(`080`: a record-less datamodel directory is listed `unfinished` with its progress, and
`rm datamodel` names it); `tests/cli/test_a_withdrawn_run_stays_findable_and_cascade_removes_all_of_it.py`
(`081`: the orphan row and the `rm run-definition` payload; the cascade on a datamodel run that
ran — records, definition, output, component gone, the user's own data untouched; a shared
component kept and attributed to the run that holds it; `--cascade` refused off `rm run`).
