# 032 — A row-contents refusal quotes one offender and reports `example_total: 0` while twenty rows are wrong

**Status:** closed 2026-09-01 by
`docs/implementations/121-a-content-check-counts-before-it-refuses.md`. The settlement went to the
code, not the promise: both content checks now scan the batch, quote up to five distinct offenders
and report the true `example_total`; the structural checks keep failing on the first bad row, which
the issue names as correct.

**Status when filed:** open. Found 2026-08-30 by the first-time-user journey in
`kaist-thesis/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-006**,
`papercut` / `message`.
**Touches:** `src/vqapr/flow/materialize.py:360-378`
(`materialize.output.instrument_unrequested`, `.instrument_duplicate`);
the `examples` / `example_total` contract in `SKILL.md`.

## What the skill promises

> *"A check on row **contents** — a duplicated key, a null in a key field — quotes up to five
> offending values and `example_total` says how many there were before truncation."*

`examples: []` is documented as fine for **structural** checks: a column's type has no offending
row to quote.

## What arrived

A DataModel emitted ~20 rows for instruments that were not in the invocation input. The refusal:

```json
{"code": "materialize.output.instrument_unrequested",
 "requirement": "DataModel output instruments must come from the invocation input",
 "observed": "_NROWS", "examples": [], "example_total": 0,
 "fix": "only emit rows for instruments passed into materialize's instruments argument",
 "explain": "component-contract",
 "source": {"file": null, "key_path": null, "line": null}}
```

One offender in `observed`, singular. `examples` empty, `example_total` **zero** — for a check whose
own documented siblings are "a duplicated key, a null in a key field", and with roughly twenty
offending values in hand.

## The mechanism, from the source

`materialize.py` raises inside the per-row loop, on the first offending instrument. That is why
`observed` is singular and `examples` is empty: the check **fails fast rather than collecting**, so
there is no set to quote and no count to report. `instrument_duplicate` two branches below has the
same shape.

So this is not a content check that took the structural path by accident. It is a content check that
cannot populate the fields its own documentation promises, because it never sees the second offender.

## Why the count is the part that matters

`example_total: 0` reads as *"zero rows were wrong"*, which is false, and it is the only quantity in
the envelope. On a model that mostly works but emits a handful of stray names, this envelope names
one and says the count is zero. **You cannot distinguish one typo from a systematic fault** — which
is the exact distinction `example_total` exists to let you make.

## Credit, because the rest of this refusal is good

`fix` is a real action, `explain` names a topic that exists, `retry_precondition` is present and
correct, and a `correlation_id` and diagnostics path were written. All six guaranteed fields are
here. This is the envelope working, which is why the one soft spot is worth filing rather than
shrugging at.

## What to settle

Whether output-contract checks should scan the batch and collect up to five offenders with a true
`example_total`, or whether fail-fast is deliberate and the `examples` / `example_total` contract
needs an exception written into it naming which checks cannot honour it. Either is fine; the current
state promises one behaviour and ships the other, and reports a false zero either way.
