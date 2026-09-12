# 099 — `check` fails with a 500 when a run's `end` falls between a day's fill and that day's decision

**Status: CLOSED 2026-09-10 -- record `237`.** Reproduced on `develop` at 0.13.0. The ordering
judgment (`_judge_execution_ordering`) read the DERIVED agenda, which `derived_agenda` cuts on
venue-local dates and keeps as a superset of `[start, end]` (`docs/issues/archive/069`); every
other reader of that agenda -- preflight's `_freeze_agenda`, the run, `_first_decision` -- slices
it to `[start, end]` first. The one judge that did not handed the `end` day's 16:30 decision to
`select_target`, which refuses a decision after `end` by contract, and the judgment blocked. It
now asks about `inclusive_slice(start, end)`, the same occurrences the run walks: 16:00 is a
valid `end` and answers clean, 23:59 is named as `execution.not_after_decision` (412). The
envelope point -- `ok: false` with `failures: []` and the cause under `blocked` -- is the
documented shape (`cli/check.py`) and was not changed here; it stays a reading note for callers.
Test: `tests/cli/test_check.py::test_an_end_between_the_last_fill_and_the_last_decision_is_answered`.

---

The report as it arrived:

| | |
|---|---|
| vqapr version | `0.11.0` |
| installed from | `../../vqapr/dist/vqapr-0.11.0-py3-none-any.whl` |
| reported | 2026-09-10 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12 / Windows 11 |

## What I was doing

A daily strategy run that must read a dataset stamped at **16:00** (a datamodel's output) and trade
on it. Deciding at 15:29 would read yesterday's stamp, so the strategy decides at **16:30**, after
the stamp, with `execution.fill.at: "15:30"` -- the first 15:30 instant after a 16:30 decision is
the NEXT session's close. Decide on t's close, fill at t+1's close.

```yaml
    agenda:   {every: 1d, at: "16:30"}
    execution: {dataset: venue-daily, trade_price: close, fill: {at: "15:30"}}
```

## What I expected

The last data day is 2026-07-28. Its 16:30 decision has no later session to fill at, so the run
must stop before it -- and must still include the 07-28 15:30 fill of the 07-27 decision. An `end`
of **2026-07-28T16:00** does both: the last fill (15:30) is inside, the last decision (16:30) is
outside. I expected that decision to be left out of the agenda.

## What happened

`vqapr check` fails, as a 500, from inside a judgment:

```
[500 judgment.blocked] every judgment answers before a run is accepted
observed: execution_ordering could not answer: ValueError: decision_time must not be after end_time
```

The full `check` envelope, verbatim:

```json
{"blocked": [{"cause": {"message": "decision_time must not be after end_time", "origin": null, "traceback": "Traceback (most recent call last):\n  File \"D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.venv\\Lib\\site-packages\\vqapr\\flow\\declaration\\judgments.py\", line 205, in judgments\n    found.extend(judge())\n                 ^^^^^^^\n  File \"D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.venv\\Lib\\site-packages\\vqapr\\flow\\declaration\\judgments.py\", line 181, in <lambda>\n    lambda: _judge_execution_ordering(definition, workspace, at, agenda),\n            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.venv\\Lib\\site-packages\\vqapr\\flow\\declaration\\judgments.py\", line 388, in _judge_execution_ordering\n    if table.select_target(\n       ^^^^^^^^^^^^^^^^^^^^\n  File \"D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.venv\\Lib\\site-packages\\vqapr\\exchange\\execution_table.py\", line 131, in select_target\n    return self.fill.select_target(\n           ^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.venv\\Lib\\site-packages\\vqapr\\exchange\\conventions.py\", line 195, in select_target\n    raise ValueError(\"decision_time must not be after end_time\")\nValueError: decision_time must not be after end_time\n", "type": "ValueError", "where": null}, "code": "judgment.blocked", "example_total": 0, "examples": [], "fix": "run `vqapr check gate-beta-001` to see the full report, then fix what stopped the judgment from answering; the exception is in `cause`", "observed": "execution_ordering could not answer: ValueError: decision_time must not be after end_time", "requirement": "every judgment answers before a run is accepted", "source": {"file": null, "key_path": "runs.gate-beta-001", "line": null}, "status": 500}], "checked": ["workspace", "run", "judgments", "preflight"], "failures": [], "ok": false, "passed": ["workspace", "run", "preflight"], "skipped": [], "stage": "check", "workspace_root": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3"}
```

Note that the failure is under **`blocked`**, with **`failures: []`**. The same command with a
different `end` reports its problems under `failures`. A caller that reads `failures` -- which is
what every other refusal teaches -- sees `ok: false` and an empty list.

## Every `end` I tried

Registered under a throwaway run id reusing the same component, judged with `check`, withdrawn:

```
2026-07-28T16:00  500 judgment.blocked   (above)
2026-07-27T23:59  412 execution.not_after_decision + 412 execution.target_outside_horizon
2026-07-28T23:59  412 execution.not_after_decision + 412 execution.target_outside_horizon
```

(A fourth candidate, 2026-07-28T15:30, printed nothing in my probe because the probe read
`failures` and not `blocked` -- which is the observation above. I did not re-capture it.)

The two 412s are right: those ends include a decision whose fill is outside the run. So for a
decide-after-close, fill-next-close daily strategy there is exactly one kind of `end` that is
correct -- between the last fill and the last decision -- and it is the one that fails with a 500.
The decision at 16:30 on the `end` date appears to be expanded into the agenda even though it lies
after `end`; I have not read the source and am not claiming where.

## Reproduction

Reproduced every time (the 16:00 case, three runs of `check`):

1. A strategy run with `agenda: {every: 1d, at: "16:30"}` and `fill: {at: "15:30"}`.
2. `end` set to the last data day at any time in [15:30, 16:30).
3. `vqapr check <run-id>` -> 500 `judgment.blocked`, ValueError, under `blocked`.

## Impact

Worked around by changing the design, not the declaration: the book now fires DAILY at **15:29**
and forms a new book only when its input has published a new cross-section; a score stamped 16:00
on t is read at 15:29 on t+1 and filled at t+1's 15:30. That can be declared to the end of the
data. The cost is that a book whose input changes quarterly is now called on every session and
holds on all but four of them a year.

`check` is the command that is supposed to make a run with a defect cost one command; here it
could not tell me what was wrong, only that one of its judgments had crashed.

## What would have prevented it

The agenda leaving out occurrences after `end` -- then 16:00 is simply a valid end. Failing that,
the ordering judgment refusing as a 4xx that names the occurrence past `end` and says to move
`end` or the decision time. And `check` putting a crashed judgment where callers look for
problems, or saying in its envelope that `blocked` exists.
