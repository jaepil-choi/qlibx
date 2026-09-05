# 069 -- the derived agenda is built three times per command, each time over every session the dataset has, and then sliced to the run's period

**Status:** **CLOSED 2026-09-04** on `fix/0.4.0-open-issues`, record `docs/implementations/149-the-open-issues-at-0.4.0.md`: `derived_agenda` cuts sessions to `[start, end]` on dates before building; `judgments()` derives the agenda once and hands it to both judges.

**Status when filed:** open. Found 2026-09-04 by the 0.4.0 spine trace
(`docs/walkthroughs/2026-09-04-spine-stepper-0.4.0.html`, scene ②), against `develop @ 2b5e842a`.
Confirmed against source the same day.

**Touches:** `src/vqapr/flow/preflight.py:51` (`derived_agenda`: `workspace.evaluation_times`
over the whole dataset, then `OperationAgenda.daily` over every one of them);
`src/vqapr/flow/judgments.py:169` (`_decide_agenda`, called from `_judge_execution_ordering`
:183 and again from `_first_decision` :364); `src/vqapr/flow/preflight.py:624` and `:705`
(`preflight_run` builds it a third time); `src/vqapr/flow/preflight.py:77` (`_freeze_agenda`
slices it to `[start, end]` only after it has been built in full).

## What was measured

Sample panel, 10 instruments × 735 sessions, a run of 15 sessions, `sys.setprofile` on:

| command | `derived_agenda` calls | ms each | share of the command's calls |
|---|---|---|---|
| `check sample-run` | 3 | 184 · 132 · 125 | `_require_identifier` 68,415 of 128,035 (53%) |
| `run sample-run` | 3 | 182 · 124 · 121 | 68,415 of 167,470 (41%) |
| `run sample-score` (datamodel) | 2 | 187 · 125 | 48,554 of 106,547 (46%) |

Each call builds 735 `OperationOccurrence`s (an id, a role, a `LocalInstantDeclaration` with
its fold and offset proof) and the agenda's content identity over them; the run then keeps 15.
On this panel that is ~0.4 s per command under the profiler. A dataset with a decade of daily
sessions and a run over one quarter pays the same shape at ten times the size, three times.

## Why

Record `148` moved the agenda from a registered declaration to a value derived from the run
(`sessions_from`, `timezone`, `at`). The three readers that used to look a registered agenda
up now each derive it, and nothing between them holds the result: `judgments` and `preflight`
are independent by design (`check` reports every defect at once), so they do not share a
frame. And `derived_agenda` takes the dataset's whole session list because `_first_decision`
and `_freeze_agenda` slice by `[start, end]` afterwards -- correct, and a full build followed
by a slice.

## What to do

- Slice before building: `derived_agenda` can take `start`/`end` and drop sessions outside
  them before `OperationAgenda.daily`, or `Workspace.evaluation_times` can take the bounds.
  The 735 → 15 cut then happens on dates, not on built occurrences.
- Build once per command: a small memo keyed by the definition's identity (sessions source,
  timezone, at, start, end) inside the command, handed to `judgments` and `preflight_run`;
  or let `preflight_run` accept an already-derived agenda and have `cli/run.py` pass the one
  `judgments` built.
- Measure on a real warehouse (2,000+ sessions) before deciding whether the first fix alone is
  enough; the sample panel says 0.4 s, the testbed's 2,378-session runs would say more.
