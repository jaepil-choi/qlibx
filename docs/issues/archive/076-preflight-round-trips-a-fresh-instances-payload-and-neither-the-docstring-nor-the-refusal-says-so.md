# 076 -- preflight round-trips a fresh instance's payload, and neither the docstring nor the refusal says so

**Status:** **CLOSED 2026-09-04 by record `152`** (one-shape campaign Step 2). All three halves:
`_validate_initial_model_state` is three named steps, `cli/run.py::preflight_refusal` carries the
`__cause__` chain in `observed`, and `run` renders a preflight `ValueError` in `check`'s own stage
and codes instead of `unhandled`. The two `authoring.py` docstrings and `SKILL.md` state the
round trip. Found 2026-09-04 by the scenario testbed run 4
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-004**), against `vqapr-0.4.0`. Confirmed
against source 2026-09-04. Two halves: a contract that is enforced and not stated, and a refusal
that drops the exception it wrapped. The second half also puts `check` and `run` on different
stages for the same refusal, which is the `012`/`015` family.

**Touches:** `src/vqapr/flow/preflight.py:160-183` (`_validate_initial_model_state`:
`save_payload` on a fresh instance, `load_payload` on a second fresh instance with those bytes,
`save_payload` again, bytes compared; every exception re-raised as one constant string);
`src/vqapr/authoring.py:811-815` (`save_payload` / `load_payload` docstrings, one line each);
`src/vqapr/cli/check.py:216-240` (`_from_python` renders `f"{type(error).__name__}: {error}"`,
never `__cause__`); `src/vqapr/cli/run.py:158` (`preflight_run` is called outside the `try`, so the
same `ValueError` reaches the envelope as `stage: unhandled`).

## What happens

A strategy whose network does not exist until its first retraining wrote `save_payload` to emit
nothing and `load_payload` to `torch.load` whatever it was given. `vqapr check` said:

```
run.check.preflight_refused
observed: "ValueError: strategy initial payload for 'ffn_k0' cannot be staged"
fix: correct the run 'ff-arm-test' so the preflight phase completes, then check again
```

`vqapr run` on the same run did not say that; it fell to `stage: unhandled`, `failures: []`,
`family: null`, with a path to `.vqapr/diagnostics/unhandled.txt`. The traceback there showed
what neither message did: `_validate_initial_model_state` calling `restored.load_payload(BytesIO(
frozen_payload))` on the empty bytes the author's own `save_payload` had just produced, and
`torch.load` raising `EOFError`. The fix on the author's side was one line -- `load_payload`
tolerates an empty source -- once they knew that a fresh instance is round-tripped before the first
callback. Nothing on the surface had said it would be.

## Why

The round trip is a real contract: the Flow relies on "a fresh instance with both restored decides
the same" (`StrategyModel` docstring), and proving it at preflight is the right time. But the
contract is stated for *restoring after a callback*; the two docstrings say "persist private
callback state" and "restore what `save_payload` wrote", and an author reading them will not expect
`load_payload` to be called before any callback has run, on bytes their own class produced in an
empty state.

The refusal is the other half. `_validate_initial_model_state` wraps every exception in one string
and `raise ... from error`, which is correct; `check`'s `_from_python` then renders only the outer
exception, so the `EOFError` and the frame it came from are lost between the raise and the
envelope. `run` does not route preflight through any renderer at all.

## What to do

- Two sentences in the `save_payload` / `load_payload` docstrings and the scaffold: "preflight
  calls `save_payload` on a fresh instance, `load_payload` on another with those bytes, and
  `save_payload` again; both must succeed and the bytes must match before the first callback. A
  class with nothing to save yet must accept an empty source."
- Carry the cause. `_from_python` should append `__cause__` (`EOFError in load_payload: Ran out
  of input`) to `observed`, and `_validate_initial_model_state` can name which of the three steps
  failed in its own message. The refusal then tells the author where to look without the
  diagnostics file.
- `run` should render a preflight `ValueError` the way `check` does (`run.check.preflight_refused`),
  not as `unhandled`. The `run` docstring already says a green `run` means what a green `check`
  means; a red one should say the same thing too.

Related: `012` and `015` (check and run disagreeing), `016` (a callback failure that dropped half
the envelope), `065` (`inputs()` also runs before memory is set, and the docs half of that was
closed by record `149` with exactly the kind of sentence asked for here).
