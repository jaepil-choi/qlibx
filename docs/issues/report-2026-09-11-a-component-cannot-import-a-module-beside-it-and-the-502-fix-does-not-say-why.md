# A component cannot import a module in its own directory, and the 502 `fix` does not say why

**Status: UNTRIAGED — reported by testbed, not yet judged by the owner.** The status is 502 with
`cause.origin: "user"`, which the report-issue-dev skill says is normally the author's to fix. It
is filed because the author's code is ordinary Python that works outside the loader, and nothing
on the surface says components cannot import their neighbours. If this is intended, the finding
is the missing sentence, not the behaviour.

| | |
|---|---|
| vqapr version | `0.14.2` |
| installed from | `vqapr-0.14.2-py3-none-any.whl` built in `vqapr/dist/`, copied into each run directory |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-ff3-testbed`, run `B-2` (sonnet, agent session); reproduced by the evaluator session on the shipped sample |
| python / OS | 3.12.13 / Windows 11 |

## What I was doing

Building the Fama-French factors through vqapr. The agent split shared code into modules next to
its components:

- `ff3/universe.py` (rebalance dates and the ticker list), imported by the DataModel `ff3/classify.py`.
- `ff3/strategy_common.py` (the base class for six portfolio strategies), imported by each leaf
  strategy.

Both are plain `import` statements of a sibling module in the same directory.

## What I expected

That a registered component could import a module sitting next to it, as any Python file run from
its own directory can. I found nothing on the public surface that says otherwise: not the `register`
help, the make-strategy and make-datamodel skills, or the refusal.

## What happened

    $ vqapr register ff3/classify.yaml
    {"correlation_id": "2b1026926e0c4ffa8b2c64292d19c8e4", "error": "VqaprError: register: 1 failure(s)\n  [502 component.construction_failed] component object must load and construct from its registered config", "failures": [{"cause": {"message": "No module named 'universe'", "origin": "user", "traceback": "Traceback (most recent call last):\n  File \"D:\\chljeffreyz\\DevProjects\\vqapr-ff3-runs\\B-2\\.venv\\Lib\\site-packages\\vqapr\\extension\\loading.py\", line 112, in _load\n    spec.loader.exec_module(module)\n  File \"<frozen importlib._bootstrap_external>\", line 999, in exec_module\n  File \"<frozen importlib._bootstrap>\", line 488, in _call_with_frames_removed\n  File \"D:\\chljeffreyz\\DevProjects\\vqapr-ff3-runs\\B-2\\ff3\\classify.py\", line 39, in <module>\n    from universe import REBALANCE_DATES\nModuleNotFoundError: No module named 'universe'\n", "type": "ModuleNotFoundError", "where": "D:\\chljeffreyz\\DevProjects\\vqapr-ff3-runs\\B-2\\ff3\\classify.py:39 (<module>)"}, "code": "component.construction_failed", "example_total": 0, "examples": [], "fix": "fix the exception raised while constructing the component from its registered config; the traceback is in `cause`", "observed": "ModuleNotFoundError: No module named 'universe'", "requirement": "component object must load and construct from its registered config", "source": {"file": "D:\\chljeffreyz\\DevProjects\\vqapr-ff3-runs\\B-2\\ff3\\classify.py", "key_path": null, "line": null}, "status": 502}], "mutation": false, "ok": false, "retry_precondition": "fix the component to match its contract, then register it again", "stage": "register", "workspace_root": "D:\\chljeffreyz\\DevProjects\\vqapr-ff3-runs\\B-2"}

`universe.py` is in the same directory as `classify.py`. The traceback shows the file loaded by
path (`spec.loader.exec_module`). The `fix` says to fix the exception, but the exception is in an
import that is correct for the file's location.

## Reproduction

1. `vqapr new sample --out ./s`, then `vqapr register ./s/sample.yaml`
2. `vqapr new strategy imp-st --dataset sample-prices --out comp/imp_st.py`
3. `comp/shared_helper.py` containing `def helper_value(): return 1`, and `import shared_helper`
   added at the top of `comp/imp_st.py`
4. `vqapr register comp/imp_st.yaml` returns 502 `component.construction_failed`, `ModuleNotFoundError:
   No module named 'shared_helper'`. A DataModel scaffold with the same import fails the same way.
5. Control: the same registration with `PYTHONPATH` set to `comp/` succeeds. The same strategy with the
   import removed also succeeds.

Reproduced 1 of 1 for a strategy and 1 of 1 for a datamodel. The envelopes are saved at
`kwam-enhanced-index/vqapr-ff3-testbed/analysis/repro/sibling_import_*.json` and
`indirect_yaml_*.json`.

## Impact

Worked around. The agent concluded that "vqapr doesn't put a component's own directory on
`sys.path`" and restructured its files. It cost several register rounds, and it contributed to a
wrong diagnosis of a different refusal: the kind-form "defines 0" refusal, filed separately as
`report-2026-09-11-register-by-kind-refuses-a-strategy-that-inherits-through-a-shared-base-and-its-fix-names-a-class-already-there.md`.
Shared helper modules are how most authors keep six nearly identical components in step.

## What would have prevented it

One of these:

- A component's directory being importable for the component.
- The make-strategy and make-datamodel skills saying it is not, and naming the supported way to
  share code (a package installed in the environment, or one file).
- The 502 `fix` naming that when the cause is a `ModuleNotFoundError` for a module that exists
  beside the component.
