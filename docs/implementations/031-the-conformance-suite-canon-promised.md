# 031 — The conformance suite canon promised

## Why this exists

Canon declares a conformance suite in five places: §10.2 says the four extension points *"enter
through the same door and pass the same conformance"*, the tree at line 2760 lists
`conformance/ runner · datamodel · strategy_model · exchange · constraint`, §10.3 decides to
*"ship the fixture builders and the conformance suite in the package"* and fixes its input as a
`ComponentRef` with `academic` and `krx` as the first two implementations to pass, and the §16
checklist requires `pytest`/`vqapr check`/`vqapr register` to call the same conformance code.

What shipped was two empty files:

```
src/vqapr/testing/__init__.py              0 bytes
src/vqapr/testing/conformance/__init__.py  0 bytes
```

A previous handoff called this *"a broken promise rather than dead scaffold"* and left it. Either
build it or withdraw the claim — the state where canon describes a feature in detail and the
package ships nothing is the one state that keeps costing, because each new reader is told to use
something that does not exist.

## What it adds that the load door does not

Registration already proves a component **loads**: fingerprint matches, object constructs, it
implements its contract type, it declares its requirements (record from `660b159`).

Loading is not conformance. A component can construct perfectly and still be uncallable, because
the methods Flow will invoke are not the methods it defined. The suite checks what loading cannot:
every method the contract declares is present, callable, and takes the parameters Flow passes
positionally.

**It found three of these in this repository on its first run.** Three test fixtures declared:

```python
def evaluate(self, account, marks):        # registered without complaint
```

against a contract that is:

```python
def evaluate(self, window, account, marks, bounds):
```

All three registered cleanly and would have failed at the first monitoring occurrence — reporting
a stage that names the run rather than the component. That is exactly the failure mode the load
door was built to prevent, one layer deeper.

## One implementation, not a parallel gate

Canon requires the three entrances to call the same code, so `_register` no longer takes a
`load=` callable. It calls `conformance(ref).raise_if_failed()`, and `conformance()` calls the same
`load_*` function registration used to call. A component cannot pass one entrance and fail another
because there is only one implementation.

A load failure **rides through with its own verdict** rather than being restated: `load_*` already
raises a typed `VqaprError` whose failures are specific, so `conformance()` re-emits those failures
unchanged. Flattening them into a generic "did not load" would lose the diagnosis the load door
spent effort producing.

The suite returns a `Diagnosis`, not a raise, so a caller collects every problem at once —
`test_every_problem_is_reported_at_once` pins two independent signature breaks in one reply.

## Its input is a `ComponentRef`, and there is no branch that can tell components apart

Canon §10.3 is specific about this, and it is why `academic` and `krx` pass their own suite in
`test_the_shipped_profiles_are_the_first_two_implementations_to_pass`: they enter as a
`ComponentRef` exactly like a user's venue, so no code path can privilege a shipped component.

`conformance` is exported from `vqapr.public` and reachable as `vqapr.testing.conformance`, because
canon's checklist requires a user to reach it *"without internal imports"*.

## What it deliberately does not check

Whether a callback returns a *useful* intent for real data is only knowable during a run against
real observations. The suite makes no claim about it and answers one question: will Flow be able to
call this component at all. Widening it to behaviour would require the fixture builders canon lists
beside it, which are not built — recorded in issue 004.

## Trade-offs

- **`Exchange` is a `Protocol`, not an ABC**, so nothing forces a registered venue to declare
  `execute`. `load_exchange` requires a shipped profile, which supplies it. It is still listed in
  `_CONTRACT_METHODS` so the check is stated in one table rather than depending on which contract
  happens to be abstract.
- **Properties are checked for presence, not signature.** `Constraint.constraint_id` is a property;
  comparing its parameters would compare the getter's, which is not the contract.
- **Three test fixtures changed.** They were wrong, not the suite — the real builtins
  (`no_short`, `single_name_cap`) already take all four parameters.
- **Canon line 4129 contradicts `scaffold.py`** and is left standing, recorded as issue 004 rather
  than resolved here: canon wants a fresh template to fail conformance, `scaffold.py` decides a
  template must run as written, and choosing between them decides what conformance *means*.

## Validation

```
uv run pytest -q                  594 passed (from 586)
uv run ruff check src/ tests/     clean
G-4 result invariance             64 fields identical
```

Eight tests in `tests/testing/test_conformance.py`, where canon §10.3 says the suite itself is
verified. The load-bearing one is
`test_a_stale_callback_signature_is_caught_though_it_constructs`: it registers a component that
passes every load-time check and still cannot receive the call Flow makes.
