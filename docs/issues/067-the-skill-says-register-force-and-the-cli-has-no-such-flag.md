# 067 -- the skill says an edited component is refused without `register --force`; there is no such flag, and a plain re-register replaces the registration and says nothing

**Status:** **CLOSED 2026-09-04** on `fix/0.4.0-open-issues`, record `docs/implementations/149-the-open-issues-at-0.4.0.md`: the skill's `--force` sentences and `vqapr remove` are gone; `Workspace.register_component` lost its dead `force` parameter; `register <kind> <id> <file>` reports `replaced: {fingerprint}` when it replaced one.

**Status when filed:** open. Found 2026-09-03 by the scenario testbed run 2, phase 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-017**), against `vqapr-0.3.0`. Confirmed
against source the same day. Same family as `025` and `030`: a sentence in the shipped skill that
the CLI no longer backs.

**Touches:** `src/vqapr/agent/skill/SKILL.md:290-297` (*"Correcting a registration during
setup"*: registering a different declaration under a taken id *"is refused"*, and the ordinary
loop is `vqapr register <file> --force`) and `:303` (*"re-register with `--force`"*);
`src/vqapr/cli/register.py` (no `--force` argument at all); `src/vqapr/workspace.py:737-765`
(`_merge_component`: *"replacement is the default"*, `force` retained and ignored -- `_ = force`);
`src/vqapr/cli/run.py:177` (the only `--force` the CLI has, which replaces a run record).

## What happens

After the F-015 fix the agent re-registered four edited strategies under their existing ids:

```
vqapr register strategy ou-k0 work/decl/ou_k0.py      ->  ok: true
vqapr register strategy ou-k0 work/decl/ou_k0.py --force
    ->  error: unrecognized arguments: --force
```

The plain command replaced the registration in place, which is what the user wanted; the skill
had said it would be refused and that `--force` was the way. Nothing in the success payload says
a previous registration was replaced or what its fingerprint was.

## Why

`_merge_component` was changed to replace by default (the comment cites the `057` shape: the
loader said "re-register", the workspace refused, and the two messages pointed at each other).
`force` stayed on the `Workspace` method as a no-op and never reached the CLI. The skill kept the
older contract. The `--force` that does exist belongs to `run`, where it discards a run record,
so a reader who finds it in `vqapr run --help` after the skill promised it on `register` is one
step from destroying the wrong thing.

## What to do

- Decide which contract is true and write it in both places. Replacement by default is the
  decision on record; then the skill's two sentences go, and `Workspace.register_component`
  loses its dead `force` parameter.
- Make the success payload say so: `replaced: {fingerprint: <old fp8>}` when an id changed
  hands, absent otherwise. A run that already pinned the old fingerprint is unaffected, and
  the payload is how the user learns which one it was.
