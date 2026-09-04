# 084 — a run definition refuses re-registration and neither refusal names the verb that would allow it

**Status:** OPEN. Found 2026-09-04 by `kwam-enhanced-index/vqapr-enhanced-index-3` (C1, and A4 for
the second half), editing a run declaration during setup. Confirmed in source on this branch.

**Touches:** `src/vqapr/workspace.py:504-524` (`register_component`, which replaces in place and
says why), against `:818-856` (`_merge_keyed`, which refuses a changed declaration for the same
`run_id`); the shipped skill's *"Correcting a registration during setup"* paragraph.

## What happens

Two registrations behave in opposite ways, and only one of them is documented.

```
vqapr register declarations/components_books.yaml   # replaced in place, however it changed
vqapr register declarations/runs_ensemble.yaml      # refused
  [workspace.run.register.conflict] run_id 'ensemble-k200' must keep its existing
  declaration or use a new identity
```

The behaviour is defensible on both sides. A component's registration is an identity whose source
an author edits constantly, and `register_component`'s docstring argues the case (`009`, Decision
2, and `067`). A run definition is the provenance of a result, so one id pointing at two
configurations would be a lie.

What is missing is that anybody says so. The skill's paragraph reads:

> Registrations are identities: one id means one declaration, and editing the thing you already
> registered is the ordinary loop: change the file and run the same `vqapr register <kind> <id>
> <file.py>` again. It replaces the registration in place, with no flag

That is about components — `<file.py>` gives it away — but it opens on "Registrations are
identities" and reads as the rule for *all* registration. The run declaration is the one an author
edits most during setup (start date, universe, strategy list, constraints), and it is the exception
nothing states.

**The refusal removes the remedy from its own list of options.** Its `fix` is *"keep the registered
declaration for 'ensemble-k200' unchanged, or choose a new run_id"* — two options, neither of which
is what the author wants. The third exists and ships:

```
vqapr rm run-definition ensemble-k200 && vqapr register declarations/runs_ensemble.yaml
```

`_merge_keyed` predates `rm` (record `139`) and was never revisited.

## The same shape, one step earlier

A related refusal has the same omission. `inputs()` is evaluated at registration, so a document
holding two runs where the second reads the first's output cannot be registered at all: the second
run's dataset does not exist until the first has run, and the first cannot run until the document
is registered. The skill does state that `inputs()` is evaluated at registration, so this is an
author's mistake — but `vqapr new run --out` scaffolds a `runs:` block that holds several runs and
invites exactly this, and the refusal says only that a dataset is unregistered. It does not notice
that **the run producing that dataset is in the document it is refusing**, which it can see.

The reporter split one file per run and lost ten minutes.

## What to do

- The run conflict's `fix` names `vqapr rm run-definition <id>` as the way to re-register the same
  id, alongside the two options it lists now.
- The skill's paragraph gains one sentence: a `runs:` declaration is the exception — withdraw it
  first.
- The unregistered-dataset refusal, when the missing dataset is produced by a run in the same
  document, says so and says to split the document.

## Related

`009` Decision 2 and `067` (why a component replaces in place), record `139` (`rm`, which is the
answer the refusal does not give), `065` (what `inputs()` can and cannot see), `071` (a refusal
naming the value and the bound).
