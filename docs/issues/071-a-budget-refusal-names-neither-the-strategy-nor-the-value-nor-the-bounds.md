# 071 -- a budget refusal names neither the strategy, nor the offending value, nor the declared bounds, and it stops the whole run

**Status:** **CLOSED 2026-09-04** on `fix/073-the-run-reports-per-strategy`, record `docs/implementations/150-the-run-reports-per-strategy.md`. The five `Rebalance` refusals name the value and the bound (`cash_weight 2.000000000001 is outside the declared budget [-1, 2]`); `SimulationFailure` carries `component_id` and a `source` whose `key_path` is `strategies.<id>` and whose `file`/`line` are the innermost frame of the author's own file; and one strategy's refusal no longer stops the others (the third bullet below, decided: no). The fourth bullet -- a rail for the signed book -- is `075`, still open.

**Status when filed:** open. Found 2026-09-03 by the scenario testbed run 3
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-018**), against `vqapr-0.3.0`. Confirmed
against source 2026-09-04; the code paths below are unchanged at `v0.4.0`. Same family as `056`
and `066`: the refusal is correct and the payload does not carry what the user needs to act on it.

**Recurred 2026-09-04** in the scenario testbed run 4 against `vqapr-0.4.0` (FINDINGS **F-010**,
and **F-005** as the same envelope around a different exception):

- F-010 is this refusal again, one session further along a different run: seventeen names all short,
  quantised weights summing to `-1.000000000001`, cash `2.000000000001` against `cash_upper = 2`,
  and the same constant string. This time it was raised inside a `--jobs 4` worker and never
  reached the parent at all (`073`); the authoring gap that produces the residual is `075`.
- F-005 is the same envelope around the author's own exception: a `decimal.InvalidOperation` from
  a callback in an eight-strategy run reported `code: simulation.callback.intent.InvalidOperation`,
  `observed: "[<class 'decimal.ConversionSyntax'>]"` (that is `str()` of the exception, which is
  all `as_dict()` carries), and `source: {file: null, key_path: null, line: null}`. Nothing in the
  payload said which of the eight strategies raised or which line of the author's file; both were
  in the diagnostics file only. So the identity ask below is not specific to the budget refusal:
  every `simulation.callback.*` failure lacks the component id and the innermost user frame.

**Touches:** `src/vqapr/authoring.py:699-718` (`Rebalance.__post_init__`, five bare
`ValueError`s); `src/vqapr/flow/context.py:437-477` (`SimulationFailure` construction --
`observed=FailureObservation(type(cause), tuple(cause.args))`, and no component identity in the
envelope); `src/vqapr/flow/callback.py:622` (`strategy_id` is in scope one layer above the raise);
`src/vqapr/evidence/artifacts.py:137,233` (`requires_replay_from_root`).

## What happens

A run of eight strategies died at one session with:

```
cash_weight is outside the declared budget
```

The refusal was right. The strategy held a fully short book, `|w|_1 = 1`, and set
`cash = 1 - sum(w)`; quantised weights summed to `-1.000000001`, so cash was `2.000000001`
against a declared `cash_upper` of `2`.

Nothing in the payload said any of that. The failure envelope carries `clock`, `root_version`,
`model_version`, `account_version`, `correlation_id`, `frozen_run_identity` and `cutoff` -- a
clock and an account version -- plus `observed`, which is `(ValueError, ("cash_weight is outside
the declared budget",))`. There is no component id, no `cash_weight` value, and no bound. With
eight strategies in the run the author had to infer the culprit from the account version and
reason the value out by hand.

`retry_precondition.requires_replay_from_root` is `True`, so the whole run stopped at the first
failing strategy: the other seven never ran, and a second registered run with the same components
failed the same way.

The four sibling raises in the same block are the same shape:

```python
raise ValueError("target_weights are outside the declared budget bounds")
raise ValueError("long_only budgets forbid negative target_weights")
raise ValueError("target_weights plus cash_weight must equal one")
raise ValueError("an empty complete position set requires cash_weight equal to one")
```

## Why

`Rebalance.__post_init__` is a dataclass validator on the authoring surface. It has the value and
the `Budget` in hand and raises a plain `ValueError` with a constant string, so
`FailureObservation` has nothing but that string to carry. The identity that would name the
culprit -- `strategy_id` -- lives one layer up in `callback.py` and is never attached, because
`_failure` builds the envelope from run and account state only.

The escalation is separate: a decision a strategy declines to make is not, on its face, a reason
to abandon the other seven strategies of the run. `requires_replay_from_root=True` is set for
every simulation failure regardless of family.

## What to do

- Put the numbers in the message. `cash_weight 2.000000001 is outside the declared budget
  [-2, 2]` costs nothing at the raise site and removes the whole inference. Same for the four
  siblings: the offending weight, its name, and the bound it crossed.
- Put the innermost frame of the author's own file into `source` (`file`, `line`) for a
  `simulation.callback.*` failure. The traceback is already walked to write the diagnostics file;
  the first frame under the component's path is the one the author needs, and it fits the existing
  `FailureSource` shape.
- Attach the component identity to `SimulationFailure`. `strategy_id` is already in scope in
  `callback.py:622`; a `component_id` field on the envelope makes an eight-strategy run
  diagnosable from the payload alone.
- Decide whether one strategy's rejected decision should stop the run. If the answer is yes, say
  so in the payload's `fix`. If it is no, the other strategies should complete and the failure
  should be reported per strategy.
- Say somewhere reachable that `Rebalance` weights are validated to the last digit, so a book
  whose weights must sum onto a bound needs exact arithmetic. `Rebalance.of` does this for the
  author, but it cannot be used for a signed book with unequal sides, which is what a
  market-neutral residual strategy is. That gap is the reason the author met this refusal at all.
