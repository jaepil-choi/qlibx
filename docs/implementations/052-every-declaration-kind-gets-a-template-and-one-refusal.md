# 052 -- Every declaration kind gets a template and one refusal

`register` understands seven section kinds. `vqapr new` scaffolded three of them and emitted
templates for two more. The remaining two -- agendas and configs -- had to be known to exist in
advance, and the run-spec template that claimed "every required key is shown" never mentioned
them. A reader who scaffolded everything offered, filled it in, and ran got
`workspace.strategy_config.register.missing` -- a section no template had ever named, after every
visible step had succeeded.

The agenda section compounded this: when a reader typed one by hand, each missing key cost a
separate register/edit/retry cycle. Four were measured -- `role`, then a wrong `role` value, then
the `from_dataset`/`sessions` XOR, then `timezone` -- because the agenda path never used the
`_require_keys` helper that datasets had received for the identical problem.

Reported as F-002 and F-003 in `kaist-thesis/vqapr-testbed/FRICTION.md`.

## What changed

### `vqapr new agendas`

A new template kind that emits `agendas` + `strategy_configs` + `valuation_configs` in one file.
They are bundled rather than three separate commands because neither half is usable alone: an
agenda nothing is bound to never fires, and a config naming an unregistered agenda is refused. The
template leads with `from_dataset`, which is the common case, and comments the `sessions`
alternative.

### Run-spec template header

The claim that "every required key is shown" is removed. The new header says "every required key
of THIS file is shown" and explicitly names `vqapr new agendas` as the source of the binding the
file itself does not perform: "naming an agenda_id here is not a binding."

### Agenda key validation

`_require_agenda_keys` pre-checks the full set -- `role`, `at`, `timezone`, and exactly one of
`from_dataset` or `sessions` -- in a single refusal, matching what `_DATASET_KEYS` does for
datasets. A role refusal names every permitted value (`strategy_callback`, `valuation`,
`monitoring`), because the obvious guess ("strategy") is wrong and no amount of guessing converges
on a vocabulary the field name argues against.

### Typed refusals for three previously bare exceptions

1. `_sessions` raised a bare `ValueError` for the `from_dataset`/`sessions` XOR violation. This
   landed in the envelope as `stage:"unhandled"` with an empty `failures[]` and a traceback file.
   Now a structured `declaration.read.key_missing` failure with `family: DATA`.

2. `_sessions` raised a bare `TypeError` for an invalid `sessions` value (e.g. a string instead
   of a list). Same envelope problem. Now `declaration.read.value_invalid`.

3. `_component` raised a bare `ValueError` for an unrecognized `kind`. `kind: model` is the
   obvious guess and it surfaced as `unhandled`. Now `declaration.read.value_not_permitted` with
   the permitted kinds as examples.

### Workspace opening order

`workspace()` was evaluated as an argument to `_agenda()`, which defeated the lazy accessor:
Python evaluates arguments before the call, so a malformed agenda in a fresh directory reported
`workspace.open.missing` and sent the reader to fix a directory when their file was what needed
editing. Now `workspace` (the callable, not the result) is passed to `_agenda`, and `_sessions`
calls it only after the keys are proven present.

### SKILL.md

Rung 1 now lists `vqapr new dataset`, `vqapr new execution-input`, and `vqapr new agendas` as
explicit steps rather than asking the reader to write declarations by hand from scratch.

### `vqapr new --help` and `vqapr --help`

The epilog and choices list include `agendas` with a one-line description.

## Trade-off

The agendas template emits `Asia/Seoul` as the timezone and a `from_dataset` placeholder. A
reader in a different timezone edits one value; a reader who needs `sessions` uncomments two lines
and deletes one. That is less universal than a dataset template's column-name placeholders, but
the alternative is emitting nothing and letting the reader discover the section from a mid-run
failure, which is what F-003 measured.

`monitoring_policies` is commented out in the template because it is optional in a run spec and
has not appeared in any testbed friction log. Adding it uncommented would require scaffolding a
monitoring agenda that no measured run has needed.

## Validation

```
uv run --no-sync ruff check src/ tests/          # clean
uv run --no-sync pytest -q                       # 703 passed
```

New tests:

- `test_one_refusal_names_every_key_an_agenda_is_missing` -- the exact F-002 scenario: one agenda
  with only `at`, expecting three distinct failures in a single structured response.
- `test_a_malformed_agenda_blames_the_file_not_the_missing_workspace` -- pins the workspace
  opening order fix.
- `test_a_component_kind_that_is_not_permitted_names_the_permitted_ones` -- `kind: model`.
- `test_a_sessions_list_that_is_not_a_list_is_refused_with_a_stage` -- `sessions: "2024-03-05"`.
- `test_every_section_a_run_needs_has_a_template` -- a guard that fails if `register` learns a
  new section and `new` does not teach it.
- `test_an_agendas_template_registers_after_its_placeholders_are_filled` -- the template emits,
  the placeholders are replaced, and `register` accepts it.
- `test_the_run_spec_template_says_naming_an_agenda_is_not_binding_it` -- pins the header fix.

The existing `test_an_agenda_must_declare_exactly_one_source_of_sessions` was strengthened from
asserting `payload["error"]` (the untyped path) to asserting `stage`, `family`, `code`, and the
specific `observed` value for the "declares both" case.
