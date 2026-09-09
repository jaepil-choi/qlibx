# 070 -- `vqapr run` opens and decodes `workspace.yaml` four times in one command

**Status:** **CLOSED 2026-09-04** on `fix/0.4.0-open-issues`, record `docs/implementations/149-the-open-issues-at-0.4.0.md`: `cli/run.py` opens the workspace once and hands it to `preflight_run` and `run`; `registered_roster` takes a `Workspace`; the roster is read once per run and travels in `RunResult.roster` to the envelope. A test counts one `Workspace.open` per `run` command.

**Status when filed:** open. Found 2026-09-04 by the 0.4.0 spine trace
(`docs/walkthroughs/2026-09-04-spine-stepper-0.4.0.html`, observation table: *"run 명령이
workspace.yaml을 네 번 연다"*), against `develop @ 2b5e842a`. The trace saw the same four on
0.3.0; the owner ruled it a defect on 2026-09-04.

**Touches:** `src/vqapr/cli/run.py:155` (`Workspace.open(project_root)`, then
`preflight_run(project_root, definition)` at `:163` with the ROOT rather than the workspace it
just opened); `src/vqapr/flow/orchestration.py:66` (`preflight_run` opens again);
`src/vqapr/flow/orchestration.py:406` (`registered_roster(root_path)` at run start, which opens
a third time in `flow/roster.py:78`); `src/vqapr/cli/run.py:220` (`_roster_envelope` calls
`registered_roster` once more after the run, the fourth).

## What was measured

Sample panel, 10 instruments x 735 sessions, a run of 15 sessions, `sys.setprofile` on:

| open | who | why it exists |
|---|---|---|
| 1 | `cli/run.py::run` | to look the definition up by id |
| 2 | `orchestration.preflight_run` | it takes a root, so it opens; `flow/preflight.py:639` would accept the workspace |
| 3 | `orchestration.run` -> `registered_roster` | the roster is read fresh at run start (issue `009`) |
| 4 | `cli/run.py::_roster_envelope` -> `registered_roster` | the envelope re-reads the roster after the run |

Each open is 0.4 ms when the pydantic document is cached and about 5 ms on the first decode
(record `145`). The cost is small on this panel; the shape is the problem.

## Why it is a defect and not a cost

- **One command, four snapshots.** The workspace is a file that other commands write. A
  `vqapr register` landing between open 1 and open 2 makes `check`-level judgments run against
  one document and preflight freeze another, and nothing says so. Four reads is four chances
  for the run to see two different workspaces and report one.
- **The roster is read twice on purpose and once by accident.** `roster.py`'s own docstring says
  *"once is literal: `roster_report` is handed what this returned rather than reading it
  again"*, and `orchestration.run` honours that (`_roster_report_or_stale(roster)`). Then
  `cli/run.py` reads it again for the envelope, with a comment explaining why a stale re-read is
  tolerable. The envelope could be built from the roster the run already held and reported.
- **`preflight_run(project_root, ...)` throws the open away.** `cli/run.py` holds a `Workspace`
  and passes the root. `flow/preflight.py::preflight_run` accepts either; the public
  `orchestration.preflight_run` accepts only a root.

## What to do

- `cli/run.py` opens once and hands that `Workspace` to preflight; `orchestration.preflight_run`
  accepts `Workspace | str | Path` the way `flow/preflight.py` already does.
- The roster read at run start travels to the envelope: `RunResult` carries the roster (or its
  report) the run used, and `_roster_envelope` reads from the result instead of the disk.
  The `stale` branch of the envelope then describes a state that cannot occur and goes.
- The `--jobs N` workers open their own workspace by design (each freezes the registered run
  again across the `spawn` boundary); that is one open per worker and is not this issue.
- Assert it: a test that counts `Workspace.open` calls across one `vqapr run` and expects one.
