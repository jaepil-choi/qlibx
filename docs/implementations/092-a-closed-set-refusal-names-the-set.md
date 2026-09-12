# 092 — A closed-set refusal names the set

**Closes:** the message half of
`docs/issues/archive/017-the-template-offers-an-account-mode-that-does-not-exist.md`, and with it the whole
issue. The template half is `docs/implementations/091`.
**Branch:** `fix/017-closed-set-refusal`.

## Why this change exists

Taking the value the template offered produced:

```json
{"code": "run.check.declaration_invalid",
 "observed": "KeyError: 'LONG_SHORT'",
 "requirement": "the spec must resolve against what the workspace has registered"}
```

`observed` carried an exception repr. The reader is told their value was rejected and left to find
the legal ones themselves — for this journey, by reading `AccountMode` in installed source. The
cause was `AccountMode[str(declared["mode"]).upper()]` in `_account`: a bare enum lookup whose
`KeyError` escaped as-is.

A closed set is the one case where a refusal can always be complete. The alternatives are known,
finite, and cheap to print.

## What changed

`_closed_set_member(enum, value, key_path=...)` in `src/vqapr/cli/run.py` replaces the raw lookup.
On a miss it raises `InputError` carrying the permitted set in `requirement`, what was written in
`observed`, the field in `source.key_path`, the members in `examples`, and the nearest legal value
in `fix`.

It takes the enum rather than being written for `AccountMode`, because a fix fitted to one field is
not a fix to the class of defect — and a test exercises it on a second enum to keep that honest.

### `register._nearest_hint` was deliberately not reused

`register.py` solves the same problem and its reasoning is worth preserving: a reader spent **six
consecutive guesses** on `fill.selector` — `close, market, close_price, last, vwap, next_open` —
because "selector" beside `trade_price` reads as *which price*, while the members `SAME_DAY` and
`NEXT_ELIGIBLE` are scheduling words. No number of guesses reaches a vocabulary the field name
argues against.

But `_nearest_hint` **lowercases its suggestion**, which is correct for a declaration
(`kind: strategy`) and wrong here: a run spec is parsed by member NAME. Reusing it produced
`set initial_account.mode to 'long_only'` — swapping one unusable value for another, which is the
exact defect this issue is about. The first draft did reuse it and the casing bug was caught before
commit; `_nearest_spec_value` is the run-side spelling, and its docstring records why the two
differ so nobody merges them later.

## Validation

**Gate:** fast + `tests/qa/test_refusal_envelope_six_fields.py` + `tests/cli/test_check.py` +
`tests/characterization/test_refusal_codes.py` with the baseline regenerated.

| check | result |
|---|---|
| `tests/cli/test_a_closed_set_refusal_names_the_set.py` (new) | 7 passed |
| named gate files | 52 passed, then green after regeneration |
| full fast suite | **1369 passed, 14 deselected** |

**Baseline drift was a pure relocation**: `run.check.judgment_blocked` moved from `run.py:349` to
`:400` because the helper was inserted above it. Same code, same file, nothing added or removed —
confirmed from the diff before regenerating rather than after.

The merge condition is verified **on two different keys**, as required: `initial_account.mode` with
the journey's own `LONG_SHORT`, and a second enum standing in for the `fill.selector` vocabulary
trap. Both produce a refusal naming the permitted set, with `key_path` naming the field and no
exception repr in `observed`. Two further tests cover the edges the condition does not name: a value
with no near miss still gets the whole list, and a permitted value is still accepted in either case
— without which a refusal that never accepts anything would satisfy every other assertion.
