# 094 — Two refusals carry status codes outside the class `report-issue-dev` assigns them

**Status: CLOSED 2026-09-10 -- record `220`.** Half code, half docs. (1) A component `path` that
resolves to nothing is `component.source_missing`, 404, at registration and at load, with a fix that
says how a relative `path` resolves; a file that exists but cannot be read stays 503. (2) 502 was
the code's design all along (`Status.CRASHED`: "the user's own code raised", record `171`); the
`report-issue-dev` table, its reference and nine skill footers said "500 or 502 is a vqapr defect"
and now say 500 is, 502 is yours (`cause.origin: "user"`, `cause.where`), 503 is the machine.
Follow-up left open: a package helper's typed refusal raised inside a user callback is classified by
frame origin as 500 and should be a 422.

Filed as `report-2026-09-09-status-codes-used-outside-their-documented-class.md`; numbered on
triage.

| | |
|---|---|
| vqapr version | `0.9.0.dev1` |
| installed from | `../../vqapr/dist/vqapr-0.9.0.dev1-py3-none-any.whl` |
| reported | 2026-09-09 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12 / Windows 11 |

## What I was doing

Following `report-issue-dev`'s decision table to decide, per refusal, whether to file a report.
The table keys entirely on `status`:

| what you saw | file a report? |
|---|---|
| `status` **500** or **502** | **Yes, always.** These mean a vqapr defect by definition |
| `status` **423** or **503** | **No.** Retry the same command unchanged. Report only if it never clears |

## What happened

Two refusals landed outside the class that table assigns them. Neither message is wrong -- both
`fix` fields are correct and both resolved the problem. The mismatch is the code.

### 1. `503` for a component source path that does not exist

Registering a shipped constraint with a path that resolved wrongly (mine: relative to the project
root when declaration paths resolve relative to the declaration's own directory):

    "requirement": "Constraint source must be a readable Python file",
    "source": {"file": "...\\vqapr-enhanced-index-3\\declarations\\.venv\\Lib\\site-packages\\
                 vqapr\\constraints\\builtin\\no_short.py"},
    "status": 503,
    "retry_precondition": "create or repair the component source, then retry"

503 is the table's "retry the same command unchanged" class. A path that does not exist never
clears by retrying. `retry_precondition` says so itself -- it names an edit, not a wait.

### 2. `502` for an exception raised by my own callback

A `StrategyModel.decide()` of mine raised `AttributeError`:

    "code": "strategy.callback.intent",
    "cause": {"origin": "user", "type": "AttributeError",
               "where": "...\\probe\\memory_probe.py:19 (decide)"},
    "requirement": "the strategy callback must return without raising",
    "fix": "your callback raised AttributeError; read `observed` for the message it carried, fix
            the component, and re-run -- registration replaces in place, so no new id is needed",
    "status": 502

The envelope is unambiguous that this is the author's code: `origin` is `"user"`, `source.file`
and `where` are my file and line, and `fix` says to fix the component. The status says the
opposite. `make-strategy`'s footer states both in adjacent sentences:

> A raise from your own file gives `source` the file and the line. Status **500 or 502 is a vqapr
> defect**: do not work around it, report it with the envelope.

The same shape appeared again for `OptimizeRefusal` raised inside a callback (also 502; filed
separately as a real defect on its own merits).

## Reproduction

Both reproduce every time:

1. Declare a constraint whose `path` does not resolve to a file; `vqapr register <decl>.yaml`
   -> 503.
2. Write a `decide()` that raises any exception; `vqapr run <run-id>` -> 502 with
   `cause.origin: "user"`.

## Impact

No wasted run -- both `fix` fields worked. The cost is to the decision table's usefulness, and it
is not hypothetical: in this same session I declined to file an upstream report about a mistake of
my own precisely because the table said "You misread the docs and the docs were right -> No", and
I trusted it. An agent applying the same table literally to a 502 files a defect report for its
own `AttributeError`, and the tracker fills with user bugs.

## What would have prevented it

Either the codes moving to the class the table describes -- a permanent input error as 400/404,
and a user-callback raise as a 4xx carrying `origin: "user"` -- or the table keying on
`cause.origin` as well as `status`, so "502 with `origin: user`" reads as "your code raised" and
"502 with `origin: null`" reads as "the package raised".

The second is the smaller change and matches what the envelopes already carry.
