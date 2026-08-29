# 068 — A constraint answers to the id it was registered under

The only crash in the whole first-time-user evidence base, and the only refusal in the surface that
was not a refusal at all.

## What it looked like from outside

```
$ vqapr check spec_c.yaml
{"ok": true, "checked": [spec, workspace, judgments, declaration, preflight],
 "blocked": [], "passed": [all five]}

$ vqapr run spec_c.yaml --run-id r2
{"ok": false, "stage": "unhandled",
 "error": "ValueError: loaded constraints must preserve FrozenRun ConstraintSet identity",
 "failures": [], "detail": ".vqapr\\diagnostics\\unhandled.txt"}
```

`check` — whose own help says it *proves a run spec is ready* — passed all five phases. `run` then
died inside `SimulationFlow.__init__` with a raw traceback, an empty `failures` list, and
`stage: "unhandled"`. Every other refusal in the package is a structured `code`/`requirement`/`fix`
triple. This one told a user the framework had broken when their registration was wrong.

The cause, established by bisecting the only variable: **the registered component id must be the
string the constraint's own `constraint_id` returns, character for character.** Registering
`NoShort` under `noshort` crashed. Registering the identical file under `no-short` — its
constructor default — ran clean, 240 occurrences, `ok:true`. Nothing in the run-spec template, in
`register --help`, or in the skill said the two ids were the same string.

## Where the check went, and why there is only one of it

`SimulationFlow.__init__` was the only party that ever asked the question, and by then the run was
being assembled. Three surfaces needed the answer earlier — `register`, `check`, and `run` — and
writing it three times would be three chances to drift.

They already share one door. `conformance` dispatches `ComponentKind.CONSTRAINT` to
`load_constraint`; `_register` runs `conformance` before anything is written; `preflight_run` loads
every declared constraint through `load_constraint`; and `check`'s `preflight` phase is
`preflight_run`. So a single check inside `load_constraint` covers all three, and there is no
second copy to fall out of step.

**It asks the loaded object, not the file.** `NoShort` takes its id as a constructor argument, and
a `constraint_id` can be assembled at runtime from anything; a check that parsed the source would
pass those and leave the crash exactly where it was. Asking the constructed object is what makes
the guard total rather than merely usual.

The refusal names both strings and three repairs:

```
component.load.constraint_id_mismatch
requirement: a Constraint must be registered under the id its own constraint_id returns
observed   : registered as 'noshort', constraint_id returns 'no-short'
fix        : register the component as 'no-short'; or change the class's constraint_id to
             return 'noshort'; or, if the class takes its id as a constructor argument,
             declare config: {constraint_id: noshort} on the registration
```

The third repair is not decoration. `_load` constructs with `candidate(**dict(ref.config))`, so a
constraint whose id is a constructor argument — which the shipped `NoShort` is — can be registered
under either spelling by declaring config. A fix naming only the first two would have sent that
user to edit a file the package ships.

## Two things red-teaming corrected

**The assembly guard is not dead, and the docstring saying so was wrong.** The first draft claimed
no CLI path reaches `_require_constraint_identity` once `load_constraint` refuses at the door. A
red-team case disproved it: a `constraint_id` returning a **different string on each access**
matches at registration, matches again under `check`, and disagrees by run assembly, tripping
`run.assembly.constraint_identity` from an ordinary `vqapr run`. A load-door check can only ask
once per load, so the assembly guard is the live backstop. Both docstrings now say so.

**A blank component id crashed in the same shape.** Registering under a whitespace-only or empty
key reached the envelope as `stage:"unhandled"` with a bare `ValueError` from `component_id()` --
a different cause, the identical prohibited shape, in the slice whose point is eliminating it.
The first fix guarded only `components:`, and re-running the red team immediately found
`datasets:` and `execution_inputs:` still crashing on the same input — a per-handler check is a
list you can be one short of. It is now one table, `_DECLARED_IDS`, naming every section whose key
becomes a typed identifier, applied **before any registration happens** so a bad key in a later
section cannot land after an earlier one was already written. Failures are collected, so a document
with two unusable keys costs one command rather than two.

Pinned by `tests/cli/test_register.py::test_an_unusable_declaration_key_is_refused_in_every_section_that_becomes_an_id`
across **all five** table entries and three spellings each, plus the two-bad-keys-one-command case.
The fifth, `strategy_configs`, was missing from the first version of that test and the completion
gate caught it — which is the same one-short failure the table exists to end, reappearing in the
test instead of the code. It is also the entry worth pinning most: for the other four a blank key
used to crash, while `Workspace.component()` already refused this one structurally, so here the
pre-pass changes *which* structured refusal fires rather than converting a crash into one.

## What happened to the two `ValueError`s

They are one function now, `_require_constraint_identity`, raising the same structured
`VqaprError` every other stage raises. The length check folded into the tuple comparison: two
different lengths are two different tuples.

No CLI path reaches it with a **stable** `constraint_id`, because `load_constraint` refuses that
mismatch at registration. A **volatile** one does reach it, which is why it stays: it is the
assembly invariant, and it is the last read before the run starts. An invariant nobody can read is
indistinguishable from a crash — which is the whole defect this record is about.

## Trade-offs

**A load failure short-circuits the conformance method checks.** `conformance` folds a loader
exception into its collector and returns without running `_check_methods`, which is pre-existing
behaviour for every load refusal. So a component with both a mismatched id and a stale `evaluate`
signature reports the id first and the signature on the next attempt. Two round trips instead of
one, in a case a real user does not reach: `vqapr new constraint` will emit a scaffold whose
component id and `constraint_id` agree by construction. The alternative — collecting the identity
finding in `conformance` while also raising it in `load_constraint` — buys one round trip and pays
with two implementations of one invariant, which is the drift this design exists to avoid.

**Three latently-invalid fixtures had to be corrected, and finding the third is what this change
is for.** All three registered a Constraint under an id it does not answer to — the exact defect —
and each had gone unnoticed because none of them ever assembled a Flow.

1. `tests/flow/test_preflight.py`'s `_component` helper hardcoded `constraint_id` as `'fixture'`
   while registering under the caller's identifier, so **every** constraint fixture built through
   `_setup` was invalid. The helper now returns the identifier it registers under.
2. `tests/testing/test_conformance.py` registered a `Limit` answering to `"limit"` under the id
   `"stale"`. That test is about which suite registration calls, not about ids, so the second
   defect was incidental and is removed.
3. `tests/characterization/refusal_codes.py` did the same, and this one mattered most, because
   **that harness's output is the oracle.** Its `stale` fixture stopped reaching `_check_methods`
   — `conformance` folds a loader exception into its collector and returns — so
   `component.conformance.signature_invalid` silently stopped being produced at runtime. The first
   regeneration of the baseline recorded that loss faithfully, which is precisely what
   `regenerate`'s own docstring forbids: *"a gate that rewrites its own oracle whenever it
   disagrees with it is not a gate."* The fixture now registers under the id it answers to, and
   `_ref` takes the filename and the component id as separate arguments so the coupling cannot
   come back.

The first two were fixed on the first pass and the third was missed; the completion-gate cleaner
and architect lanes both found it independently.

## Validation

```
uv run pytest tests/ -q          # 1306 passed, 13 deselected, ~84s   (1298 at 7ae3d3af)
uv run pytest tests/ -q -m ""    # the full suite including all 13 slow journeys
```

The arithmetic, because a count that does not close is a count nobody can check: **1298 + 7 new
test functions + 1 = 1306.** The `+1` is not a test anyone wrote —
`tests/characterization/test_fix_is_not_a_restatement.py` parametrizes over every `Failure.bounded`
call site by source line, so the new declaration-key refusal added a case to it. That case passes,
which is its own small result: the new `fix` string is not its `requirement` restated.

Seven tests pin the acceptance cases. Three were added after the completion gate found that cases
2 and 4 were asserted *near* their surface rather than at it, and that the declaration-key refusal
had shipped with no regression test at all:

- `tests/cli/test_commands.py::test_a_constraint_that_slipped_past_registration_is_refused_by_check_not_by_a_crash`
  — case 2 at the verbs a user types: a mismatched constraint planted through the `Workspace` API
  (the route registration does not cover, which the criterion itself anticipates), then `check`
  returning `ok:false` with the code and `run` refusing with `stage != "unhandled"` and a non-empty
  `failures` list.
- `tests/cli/test_commands.py::test_a_constraint_registered_under_the_id_it_answers_to_still_runs`
  — case 4's other half: the shipped `NoShort` registered as `no-short` runs end to end with
  occurrence, account and run-state counts identical to the unconstrained run. Without it, a check
  that refused everything would pass the refusal tests just as well.
- `tests/cli/test_register.py::test_an_unusable_declaration_key_is_refused_in_every_section_that_becomes_an_id`
  — the blank-key refusal, across all five sections whose key becomes a typed identifier and three
  spellings each, asserting the stage, the exact code, and that `source.key_path` names the
  offending section; plus the case proving two bad keys cost one command rather than two.

- `tests/cli/test_register.py::test_a_constraint_registered_under_an_id_it_does_not_answer_to_is_refused`
  — the mismatch is refused at the door, names both ids and all three repairs, and nothing is
  written to the workspace.
- `tests/cli/test_register.py::test_a_constraint_id_computed_at_runtime_is_still_checked` — a
  `constraint_id` built by `'-'.join([...])`, invisible to any static read, is still caught.
- `tests/cli/test_register.py::test_the_shipped_no_short_registers_under_the_id_it_answers_to` —
  the reported case, both halves plus the config repair: `noshort` refused, `no-short` accepted,
  `noshort` with `config: {constraint_id: noshort}` accepted.
- `tests/flow/test_preflight.py::test_a_constraint_that_does_not_answer_to_its_id_is_refused_before_the_run`
  — the case `register` does not cover, a workspace populated directly, refused at the phase
  `check` runs.

`tests/acceptance/test_time_002.py::test_shared_constraint_identity_is_the_only_constraint_authority`
now asserts the structured refusal and the two ids it reports, rather than matching a fragment of a
bare `ValueError` message.

`tests/cli/test_check.py`'s pinned inventory is **unamended**: the new codes live in `loading.py`,
`simulation.py` and `cli/register.py`, not in `check.py`'s `CODES`, so `check` still settles
exactly eight judgments.

The refusal-code baseline was regenerated deliberately with
`python -m tests.characterization.refusal_codes`. Stated exactly, because an earlier draft of this
record described it as "the two codes added here" and that was not the whole diff: against
`7ae3d3af`, `runtime_codes` **gains `component.load.constraint_id_mismatch` and loses nothing**,
and `coverage_gap` gains `run.assembly.constraint_identity`. The assembly guard is declared and not
runtime-observed by that harness, which is accurate — it is reachable only through a volatile
`constraint_id` or a direct `SimulationFlow` construction, not through the paths the harness walks.
