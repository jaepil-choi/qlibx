# 028 — A module below the CLI reaches up through the facade, and no test counted it

**Status when filed:** open. Found 2026-08-30 by an owner-requested boundary audit of `src/`,
against `develop@ad4565f9`, while the 015–027 campaign was still running. **Not a journey
finding** — no first-time user could see this. It is a regression introduced by this campaign's own
first story, and the mechanism that was supposed to catch it is prose.
**Touches:** `src/vqapr/flow/judgments.py:29`; `docs/design/agent-first-surface.md`
("The ruling — 2026-08-28"); `tests/boundaries/`.

## The tripwire moved

The ruling of 2026-08-28 defines exactly one instrument for this: the count of modules under `src/`
containing a real `import` statement for `vqapr.public`, string literals excluded by an AST walk. It
records **verified value: 12**, names the twelve, and gives the command.

Run today, that command returns **13**. The diff is one file:

```
_internal/constraint_bridge.py   _internal/registration_bridge.py   _internal/run_bridge.py
_internal/schedule_bridge.py     _internal/strategy_bridge.py       _internal/venue_bridge.py
agent/sample/exchange.py         agent/sample/journey.py            cli/check.py
cli/register.py                  cli/run.py                         project.py
flow/judgments.py                                                   <-- new
```

`src/vqapr/flow/judgments.py:29` is `from vqapr.public import Workspace`. It arrived in
`1a0f58c1` — *"Judgments move below the verbs that ask them"*, the pure-move half of `docs/issues/015`.

The move itself was correct and its stated criterion held: no module under `flow/` imports `cli`.
Nothing in that criterion mentioned `public`, so the import style travelled down with the code. The
line it came from is `cli/check.py:45`, `from vqapr.public import Workspace, preflight_run`, where it
was legal because `check` is a CLI verb and the CLI is the facade's caller.

## The name it reaches for is one the facade deliberately withholds

`tests/boundaries/test_public.py` asserts, in as many words:

```python
assert "Workspace" not in public.__all__
assert "SimulationFlow" not in public.__all__
assert "DuckDbObservationStore" not in public.__all__
```

`public.py:131` imports `Workspace` for its own `run()` to use and keeps it out of the surface on
purpose. `judgments.py` gets it anyway, because `__all__` governs `import *` and nothing else. **The
one boundary the suite states outright is the one this import walks through**, and it stayed green,
because a passing `__all__` assertion and a working `from vqapr.public import Workspace` are not in
tension — they are the same fact seen from two sides.

Every sibling in the same layer spells it the other way:

| module | how it gets `Workspace` |
|---|---|
| `flow/materialize.py:36` | `from vqapr.workspace import Workspace` |
| `flow/preflight.py:32` | `from vqapr.workspace import Workspace` |
| `flow/views.py:11` | `from vqapr.workspace import Workspace` |
| **`flow/judgments.py:29`** | **`from vqapr.public import Workspace`** |

## What it costs, measured

Modules resolved into `sys.modules` by a single import, one clean subprocess each:

| import | `vqapr.*` modules loaded |
|---|---:|
| `vqapr.workspace` | 39 |
| `vqapr.flow.preflight` | 67 |
| `vqapr.public` | 102 |
| **`vqapr.flow.judgments`** | **104** |

Importing one judgment module pulls in more of the package than importing the whole facade does.
`tests/boundaries/test_capability_absence.py` is built on the principle that *"the boundaries worth
keeping are already enforced by the absence of a path"*; this adds a path from `flow/` to everything.

It is also one line away from a cycle. `public.py` imports `flow.simulation`, `flow.run`,
`flow.materialize`, `flow.preflight`, `flow.run_records` and `flow.run_state`; `flow.judgments` now
imports `public`. The two do not meet only because `public.py` has no reason to import `judgments`
yet — and `run` performing the judgments (`docs/issues/015`) is exactly the kind of change that
would give it one.

## Why nothing caught it

The ruling is canonical — `.agent/project.yaml` names it `surface_design` — and it is still only
prose plus a shell command a human has to remember to run. The three boundary tests each watch
something else:

- `test_public.py` pins the **contents** of `__all__`, a 130-name tuple. Adding an importer does not
  touch it.
- `test_capability_absence.py` probes five leaves — `transforms.cross_section`,
  `transforms.fama_french`, `transforms.neutralize`, `analysis.signal`, `analysis.performance`.
  `flow/` is on its `FORBIDDEN` list as a thing leaves must not reach, never as a thing to check.
- `test_runtime.py` watches the runtime boundary.

So the gate for 015a — fast suite, `test_refusal_codes`, `test_check`, `test_check_collects`,
`test_check_does_not_mutate` — was passed by a change that moved the one number the ruling exists to
protect. The ruling anticipated this in general terms: it records that *"the next twenty commits
added three more `vqapr.public` importers"* after the knowledge was written down in a handoff. This
is the twenty-first, added after it was written down canonically. **Being canonical was not enough;
the next thing to try is a test.**

## What closes it

Two halves, and the second is the one that matters.

1. **The import.** `flow/judgments.py:29` becomes `from vqapr.workspace import Workspace`, matching
   its three siblings. The tripwire returns to 12 and the module stops dragging the facade behind
   it. No behaviour changes — `public.py:131` re-exports the same class object.

2. **The tripwire becomes a test.** A boundary test that fails when the AST importer count moves,
   seeded with the twelve the ruling already enumerates, so the next addition is a red suite rather
   than an audit two days later. A count alone is enough; it does not need to judge which imports are
   legitimate, only to make an addition a decision somebody takes on purpose.

Half 1 without half 2 fixes this instance and leaves the next one to chance. Half 2 without half 1
pins the wrong number.

## What this issue does not claim

The five frozen modules are unchanged. Re-measured on 2026-08-30 against the ruling's own list:
`project.py` still has exactly one importer (`__init__.py`, `vqapr.open()`), `simulation.py` only
`project.py`, `venues.py` only `_internal/venue_bridge.py`, `materialization.py` still has no
`import` statement anywhere in `src/` and is reachable only as a lazily resolved capability name.
**The freeze held. Only the `vqapr.public` count moved**, which is precisely the gap the ruling's
"What the tripwire does not watch" section warned would be read the wrong way round.

`G008` is not in scope here and this file does not touch its admission conditions.
