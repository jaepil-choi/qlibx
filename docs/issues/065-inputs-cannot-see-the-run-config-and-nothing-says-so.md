# 065 -- `inputs()` runs before `initial_model_memory` is set, nothing says so, and one class cannot be registered under several ids with different settings

**Status:** open. Found 2026-09-03 by the scenario testbed run 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-014**), against `vqapr-0.3.0`. Confirmed
against source the same day. Filed as a docs defect with a design question attached.

**Touches:** `src/vqapr/flow/preflight.py:500-504` (`loaded_strategy.requirements()` before any
memory is applied); `src/vqapr/flow/orchestration.py:248-255` (`strategy.requirements()` on line
248, `strategy.memory = normalize_memory(layer.initial_model_memory)` on line 255);
`src/vqapr/cli/new.py:248` (`initial_model_memory: {}` per strategy in the run template);
`src/vqapr/agent/skill/SKILL.md:57` (*"The file must define exactly one StrategyModel subclass"*).

## What happens

A 2 x 2 grid -- two signals x two residual datasets -- is one strategy with four settings. The run
template shows `initial_model_memory: {}` per strategy and `show strategy` records a `config: {}`,
so a per-strategy configuration channel visibly exists. But memory is restored *"before every
decide()"*, the skill says nothing about whether `inputs()` may depend on it, and a file must hold
exactly one class. The safe reading was code generation: a template and a generator wrote
`ou_k0.py`, `ou_k5.py`, `fft_k0.py`, `fft_k5.py`, four registrations, four fingerprints, four
copies of 200 lines differing in four constants.

The safe reading was right. Both `preflight` and `orchestration` call `requirements()` -- which
calls `inputs()` -- before `memory` is assigned, so an `inputs()` that reads memory sees `None`.
Nothing documents that order.

## What to do

- Say it in the skill and in `Model.inputs`'s docstring: `inputs()` is evaluated at registration
  and preflight with no memory and no config, so the reads a model declares cannot depend on
  either; a family of settings is a family of registered components.
- Then decide the design question this leaves: whether a component id may bind a class plus a
  config (`register strategy ou-k5 ou.py --config k=5`) so one file serves several ids and one
  fingerprint covers the class, or whether four files is the intended shape and the skill should
  show the template pattern. `040` closed on strategy configs being keyed by component id; this is
  the next question on that axis.
