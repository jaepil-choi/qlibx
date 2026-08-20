# 032 — Arity is the contract, not spelling

## Why this exists

Record 031 built the conformance suite and left one question open as issue 004: canon line 4129
wanted `vqapr new`'s template to **fail** conformance, `scaffold.py` decided a template must **run
as written**, and choosing between them decides what conformance *means*.

The owner decided: **the template must pass.** Conformance means *"does this component return the
expected output type"* — and the honest consequence of that definition is that very little is
decidable before a run. A do-nothing component that returns a valid `NoDecision` is conformant.

Measuring the suite against that definition exposed that it was answering neither question
correctly.

## What was measured

Four strategies, judged by `conformance()` and then actually called the way Flow calls them:

```
component     conformance            Flow can call it?
do_nothing    PASS                   yes -> NoDecision      correct
renamed       FAIL signature_invalid yes -> NoDecision      FALSE POSITIVE
wrong_arity   FAIL signature_invalid NO (TypeError)         correct, by accident
wrong_return  PASS                   yes -> dict            FALSE NEGATIVE
```

Rows two and four are the finding. The suite **refused working code** and **accepted the exact
mistake the owner's definition names**. Row three was caught only because the parameter *names*
differed; it would have been caught for the wrong reason.

`renamed` is `def on_occurrence(self, ctx)`. Flow calls it positionally:

```python
self._strategy.on_occurrence(StrategyModelContext(...))   # simulation.py:1182
```

That call lands identically whether the parameter is spelled `context` or `ctx`. Refusing it
punished a legal rename, and the same file's docstring already said *"Flow calls these
positionally"* — the check contradicted its own stated reason for existing.

## The same bug existed twice

Fixing `conformance()` alone did not change the measured result. The failure code was
`component.load.signature_invalid`, not `component.conformance.signature_invalid`:
`extension/loading.py` carried its own copy of the name comparison.

This matters more than the duplication itself. The suite's module docstring claims it is *"a
superset of the load, never a copy of it"*, and canon §10.2 requires every entrance to call the
same conformance code so a component cannot pass one and fail another. Two independent
implementations of the same check is precisely the state both documents forbid.

The arity judgement now has **one definition**, in the lower layer:

```python
loading.positional_arity(target)        -> (required, capacity)   capacity -1 == *args
loading.accepts_contract_call(impl, contract) -> bool
```

`conformance()` imports it. The load door and the suite cannot disagree because there is nothing
left to disagree with.

## What the check now decides

**Can Flow make this call?** Not *"is it spelled the way the ABC spells it"*.

- a renamed parameter passes — the call is identical
- an extra **required** parameter fails — the call cannot land
- an extra parameter **with a default** passes — the call still lands
- `*args` passes — it absorbs any arity
- keyword-only parameters are ignored — Flow never passes one

## Why the return type is not checked here, and where it is checked instead

The owner's definition of conformance is the return type. It is not decidable before a run:
an annotation can lie, and most components declare none. Checking annotations would trade a real
verdict for a guess and would reject the unannotated style the codebase already uses
(`test_an_unannotated_callback_is_accepted`).

The Flow already takes that verdict at the call site, where the returned value actually exists:

| kind | where the returned value is judged |
|---|---|
| StrategyModel | `validate_economic_intent(result)` — `simulation.py` |
| DataModel | `_validated_output(raw_rows, ...)` — `materialize.py` |
| Constraint | `isinstance(bounds, ConstraintBounds)` — `constraints/evaluation.py:111` |

So the division of labour is: **arity before the run, value during it.** Both are real checks;
neither can do the other's job. Widening either into the other's territory is what produced the
false positive and the false negative above.

## `vqapr check` is not built, deliberately

Canon line 4130 named three entrances. Two exist. The third was never built, and the owner asked
whether it has real benefit before item 2 proceeds — it does not:

- `register` already calls `conformance()`, so the check runs at the moment that matters
- a component that is not registered is not yet something Flow can run
- the remaining question — the return type — is runtime-only and no CLI command can answer it

A third entrance would give the same answer under a different name, and would be one more surface
that can drift from the other two. Canon now names **two** entrances.

## Trade-offs

- **A component that drops to zero required parameters passes if the contract has one.**
  `required <= wanted <= capacity` allows `def project(self, *args)`. That is correct — it
  receives the call — but it means arity is a *satisfiability* check, not an exactness check.
- **The failure message no longer names the expected parameters.** It reports counts
  (`must accept 5 positional arguments`). Names were the wrong contract, so reporting them would
  re-teach the thing this record removes.
- **One test was inverted, not deleted.** `test_a_renamed_callback_parameter_is_refused` became
  `..._is_accepted`, and its docstring records that it once asserted the opposite and why. A
  deleted test leaves no trace of a reversed decision.
- **Canon lines 4129/4130 were marked `[x]` with their withdrawal reason inline** rather than
  removed. Line 4129 was the only place canon stated a fresh template is incomplete; the marked
  line in `scaffold.py`'s output carries that signal instead.

## Validation

```
uv run pytest -q                  599 passed (from 594)
uv run ruff check src/ tests/     clean
```

Five new tests. The load-bearing ones:

- `test_the_scaffold_registers_as_written` (`tests/extension/test_all_four_doors.py`) — makes the
  owner's decision executable for both scaffolded kinds, so canon and `scaffold.py` cannot drift
  apart again silently.
- `test_a_renamed_parameter_passes_because_flow_calls_positionally` — the false positive.
- `test_a_star_args_component_passes_and_a_short_one_does_not` — the boundary in one test.
- `test_an_optional_extra_parameter_passes` — a default-valued extra is not a break.
- `test_a_renamed_callback_parameter_is_accepted` (`tests/extension/test_strategy_registration.py`)
  — the same property at the load door, which is where the duplicate check actually lived.

`test_an_extra_required_parameter_is_refused` was left untouched and still passes: it is the
evidence that widening the rule did not blunt it.
