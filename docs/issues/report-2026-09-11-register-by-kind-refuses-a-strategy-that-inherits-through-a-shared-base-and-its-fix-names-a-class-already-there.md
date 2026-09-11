# `vqapr register strategy <id> <file>` refuses a strategy that inherits `StrategyModel` through a shared base, and its `fix` says to add a class the file already has — the YAML route registers the same file

**Status: CLOSED 2026-09-11 — record `252`** (fixed on the owner's instruction, unnumbered). When the parse finds no subclass, the kind route asks the loaded module by the object, as the YAML route does.

| | |
|---|---|
| vqapr version | `0.14.2` |
| installed from | `vqapr-0.14.2-py3-none-any.whl` built in `vqapr/dist/`, copied into each run directory |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-ff3-testbed`, run `B-2` (sonnet, agent session); reproduced by the evaluator session on the shipped sample |
| python / OS | 3.12.13 / Windows 11 |

## What I was doing

Building the Fama-French factors through vqapr, with six StrategyModels, one per 2×3 portfolio,
that differ only in which bucket they hold. The agent put the logic in one base class,
`strategy_common.Ff3Portfolio(va.StrategyModel)`, and wrote six one-line leaf files:
`import strategy_common` and then `class Ff3S1(strategy_common.Ff3Portfolio): BUCKET = "S1"`.
The comment in `strategy_common.py` shows it chose `import strategy_common` over
`from strategy_common import Ff3Portfolio` deliberately, so that the leaf's own namespace holds
exactly one StrategyModel subclass. It registered each leaf with the component-kind form of
`register`.

## What I expected

`vqapr register --help` gives two routes for the same thing: `declaration` is "path to the
declaration YAML, or the component kind (compliance, datamodel, strategy) when registering a .py
directly". The refusal's own requirement is "the file must define exactly one StrategyModel
subclass", and `Leaf` is exactly one, reached through a base class. So I expected both routes to
accept the file.

## What happened

With the base module importable (`PYTHONPATH` set to the component directory):

    $ vqapr register strategy leaf comp/leaf.py
    {"correlation_id": null, "error": "InputError: the file must define exactly one StrategyModel subclass", "failures": [{"cause": {"message": null, "origin": null, "traceback": null, "type": null, "where": null}, "code": "argument.value_invalid", "example_total": 0, "examples": [], "fix": "add a `class Leaf(StrategyModel):` to leaf.py", "observed": "comp\\leaf.py defines 0", "requirement": "the file must define exactly one StrategyModel subclass", "source": {"file": "comp\\leaf.py", "key_path": null, "line": null}, "status": 400}], "mutation": false, "ok": false, "retry_precondition": "add a `class Leaf(StrategyModel):` to leaf.py", "stage": "usage", "workspace_root": "C:\\Users\\...\\scratchpad\\repro\\indirect"}

The `fix` asks for `class Leaf(StrategyModel):`, and the file already defines `class Leaf`, which is
a `StrategyModel`. Taken literally, the fix would make the file define two.

The same file, declared in YAML (`components: {leaf: {kind: strategy, path: leaf.py,
object_name: Leaf}}`) with the same `PYTHONPATH`, registers:

    $ vqapr register comp/leaf.yaml
    {"ok": true, "registered": {"components": ["leaf"]}, ...}

In the FF3 workspace the kind form refused all six leaves the same way (`observed: "ff3\\strategy_S1.py
defines 0"`, `fix: "add a \`class Ff3S1(StrategyModel):\` to strategy_S1.py"`, and so on for S2…B3).
The agent read the refusal as "a `ModuleNotFoundError` is being masked". The reproduction shows the
refusal is the same whether or not the import resolves.

## Reproduction

1. `vqapr new sample --out ./s`, then `vqapr register ./s/sample.yaml`
2. `vqapr new strategy tmp-st --dataset sample-prices --out comp/tmp_st.py`; rename its class to
   `CommonBase` and save the file as `comp/strategy_common.py`.
3. `comp/leaf.py`:

        import strategy_common


        class Leaf(strategy_common.CommonBase):
            """One-line subclass of a shared base, as in a six-leg factor build."""

4. Register it four ways:

| route | base importable? | result |
|---|---|---|
| `vqapr register strategy leaf comp/leaf.py` | no | 400 `argument.value_invalid`, "defines 0", the fix above |
| `vqapr register strategy leaf comp/leaf.py` | yes (`PYTHONPATH=comp`) | **400, same refusal** |
| `vqapr register comp/leaf.yaml` | no | 502 `component.construction_failed`, `ModuleNotFoundError: No module named 'strategy_common'` (filed separately) |
| `vqapr register comp/leaf.yaml` | yes | **ok** |

Reproduced 1 of 1 for each row. All four envelopes are saved at
`kwam-enhanced-index/vqapr-ff3-testbed/analysis/repro/indirect_*.json`.

## Impact

Worked around, after six refusals in one loop and a wrong diagnosis on the way. Two registration
routes reach opposite verdicts on the same file, and the kind route's `fix` points at a change
that would break the file. A shared base class is the natural way to write six portfolio legs,
so anyone who builds factors this way hits it.

## What would have prevented it

The kind route recognising a subclass the same way the YAML route loads it, by the object rather
than by the literal base name. Failing that, a `fix` that names the YAML route with `object_name`,
instead of asking for a class the file already has.
