# 089 — The documented way to keep state between decisions cannot run: `self.memory` is `None` on the first callback

**Status: CLOSED 2026-09-10 -- record `215`.** Owner ruling: the code was the smaller change and
the prose was right. An undeclared opening memory is `{}` at every layer (`StrategyEntry`,
`DataModelEntry`, `FrozenStrategy`, `FrozenDataModel`, `RunStateRepository`), a declared `null`
reads as the same `{}`, and the documented example runs on session one as written.
`memory-and-payload.md` says so. Cost accepted: every run identity that folded a `None` opening
memory changes; `docs/releases/0.11.0.md` carries the migration step. The 502 footnote is `094`.

Filed as `report-2026-09-09-strategy-memory-is-none-on-the-first-callback.md`; numbered on triage.

| | |
|---|---|
| vqapr version | `0.9.0.dev1` |
| installed from | `../../vqapr/dist/vqapr-0.9.0.dev1-py3-none-any.whl` |
| reported | 2026-09-09 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12 / Windows 11 |

## What I was doing

Writing a StrategyModel that rebalances when a new monthly signal cross-section appears and holds
in between. That needs one fact carried across callbacks -- which formation the book was last
built on -- so I followed the `make-strategy` skill to `references/memory-and-payload.md`.

## What I expected

That reference's "`self.memory` -- strict JSON" section says:

> Restored before every `decide()`, snapshotted after. Read it, change it, leave it; there is
> nothing to save explicitly.
>
> ```python
> def decide(self, call):
>     seen = self.memory.setdefault("sessions", 0)
>     self.memory["sessions"] = seen + 1
> ```

I read "restored before every `decide()`" plus an example that calls `.setdefault` unguarded as
saying `self.memory` is a dict on every callback, empty on the first one.

## What happened

`self.memory` is `None` on the first callback, so the documented example raises on session one of
every run. I copied that snippet verbatim into a strategy with nothing else in it:

```python
class MemoryProbe(va.StrategyModel):
    def inputs(self):
        return {
            "bench": va.DatasetInput(
                dataset_id="k200-benchmark",
                fields=("benchmark_weight",),
                lookback=va.CalendarLookback(days=7, timezone="Asia/Seoul"),
            )
        }

    def decide(self, call):
        seen = self.memory.setdefault("sessions", 0)
        self.memory["sessions"] = seen + 1
        return va.Hold(reason="counting sessions")
```

A six-session run over forty instruments fails immediately. The envelope, verbatim:

```json
{"correlation_id": "9b23ad926a60bbf0dc8804bdcdac87cc5ba8f9f8345e188f199dbe7e9188cadb", "error": "1 of 1 strategies failed: memory-probe; the other 0 completed and their records stand", "failures": [{"cause": {"message": "'NoneType' object has no attribute 'setdefault'", "origin": "user", "traceback": "Traceback (most recent call last):\n  File \"D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.venv\\Lib\\site-packages\\vqapr\\flow\\strategy\\callback.py\", line 273, in _callback_intent_boundary\n    yield\n  File \"D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.venv\\Lib\\site-packages\\vqapr\\flow\\strategy\\callback.py\", line 147, in dispatch\n    result = self._context.strategy.decide(\n             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\probe\\memory_probe.py\", line 19, in decide\n    seen = self.memory.setdefault(\"sessions\", 0)\n           ^^^^^^^^^^^^^^^^^^^^^^\nAttributeError: 'NoneType' object has no attribute 'setdefault'\n", "type": "AttributeError", "where": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\probe\\memory_probe.py:19 (decide)"}, "code": "strategy.callback.intent", "example_total": 0, "examples": [], "fix": "your callback raised AttributeError; read `observed` for the message it carried, fix the component, and re-run -- registration replaces in place, so no new id is needed", "observed": "'NoneType' object has no attribute 'setdefault'", "requirement": "the strategy callback must return without raising", "source": {"file": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\probe\\memory_probe.py", "key_path": "strategies.memory-probe", "line": 19}, "status": 502, "strategy": "memory-probe"}], "mutation": false, "ok": false, "retry_precondition": null, "roster": {"known": false, "note": "no instrument roster is registered, so every fill records kind: None and the report's cost by kind shows one 'unknown' bucket; register one with `vqapr register <instruments>.yaml`"}, "run_id": "memory-probe-run", "stage": "run.strategy_failed", "store_root": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.vqapr", "strategies": {"memory-probe": {"at": {"account_version": 0, "clock": "2024-01-02T15:29:00+09:00", "cutoff": "2024-01-02T15:29:00+09:00", "frozen_run_identity": "9b23ad926a60bbf0dc8804bdcdac87cc5ba8f9f8345e188f199dbe7e9188cadb", "model_version": 0, "pending_id": null, "root_version": 0}, "component_id": "memory-probe", "correlation_id": "9b23ad926a60bbf0dc8804bdcdac87cc5ba8f9f8345e188f199dbe7e9188cadb", "failures": [{"cause": {"message": "'NoneType' object has no attribute 'setdefault'", "origin": "user", "traceback": "Traceback (most recent call last):\n  File \"D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.venv\\Lib\\site-packages\\vqapr\\flow\\strategy\\callback.py\", line 273, in _callback_intent_boundary\n    yield\n  File \"D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\.venv\\Lib\\site-packages\\vqapr\\flow\\strategy\\callback.py\", line 147, in dispatch\n    result = self._context.strategy.decide(\n             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\probe\\memory_probe.py\", line 19, in decide\n    seen = self.memory.setdefault(\"sessions\", 0)\n           ^^^^^^^^^^^^^^^^^^^^^^\nAttributeError: 'NoneType' object has no attribute 'setdefault'\n", "type": "AttributeError", "where": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\probe\\memory_probe.py:19 (decide)"}, "code": "strategy.callback.intent", "example_total": 0, "examples": [], "fix": "your callback raised AttributeError; read `observed` for the message it carried, fix the component, and re-run -- registration replaces in place, so no new id is needed", "observed": "'NoneType' object has no attribute 'setdefault'", "requirement": "the strategy callback must return without raising", "source": {"file": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3\\probe\\memory_probe.py", "key_path": "strategies.memory-probe", "line": 19}, "status": 502}], "kind": "PRE_COMMIT", "mutation": false, "retry_precondition": {"required_pending_id": null, "requires_replay_from_root": true}, "stage": "simulation.callback.intent", "status": "failed"}}, "workspace_root": "D:\\chljeffreyz\\DevProjects\\kwam-enhanced-index\\vqapr-enhanced-index-3"}
```

Before copying the doc's example I had confirmed the value directly, with a probe that raised its
own state rather than assuming it: `observed` came back
`"call 1: type=NoneType value=None"`.

## Reproduction

Reproduced every time (11 of 11 strategies in my own run, then 1 of 1 in the minimal probe above):

1. Register a StrategyModel whose `decide()` touches `self.memory` with a mapping method.
2. Register any run naming it.
3. `vqapr run <run-id>` — fails on the first callback with `AttributeError`.

Guarding the read (`(self.memory or {}).get(...)`) fixes it, and assignment
(`self.memory = {...}`) works normally from then on.

## Impact

Cost one full 11-strategy run and the time to isolate it. It is cheap to work around ONCE KNOWN;
the expense is that the reference's example is the thing a reader copies, and it is the one shape
that cannot work.

It is also silent until execution. `vqapr check <run-id>` returned `ok: true` for the run
containing all eleven of these strategies -- preflight proves `save_payload` / `load_payload`
before the first callback, which set my expectation that `self.memory` was equally proven.

## What would have prevented it

Either initialising `self.memory` to `{}` before the first callback so the documented example
runs, or -- if `None` is deliberate, meaning "no snapshot has been taken yet" -- saying so in
`memory-and-payload.md` and writing the example defensively:

```python
def decide(self, call):
    memory = self.memory or {}
    seen = memory.get("sessions", 0)
    self.memory = {**memory, "sessions": seen + 1}
```

The first is the smaller change and matches what the prose already promises.

## One more thing, not the subject of this report

The failure carries **status 502**. `report-issue-dev`'s decision table says 500 and 502 "mean a
vqapr defect by definition", while `make-strategy` says a raise from the author's own file gives
`source` the file and the line -- which is what happened here; `origin` is `"user"`, `source.file`
is my probe and `fix` correctly says "your callback raised AttributeError ... fix the component".
An agent following the table literally files a defect report for its own `AttributeError`. Filed
separately so this report stays about the documented example.
