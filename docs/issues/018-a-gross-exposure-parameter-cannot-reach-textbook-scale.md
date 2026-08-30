# 018 — `invested` is gross exposure with an undocumented ceiling of 1

**Status when filed:** open. Found 2026-08-30 by the final first-time-user journey in
`kwam-enhanced-index/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-006**
(`slowed`) with **U-001** (`urge`) as its consequence.
**Touches:** `src/vqapr/authoring.py:670` and the `Rebalance.of` docstring above it.

## What the docstring promises

The reporter expected `invested="2"` — 1.0 of NAV long and 1.0 short, the self-financing scale a
published SMB or HML series is quoted at — because `Rebalance.of`'s own docstring frames the
parameter as gross and works a long/short example through it:

> `invested` is GROSS exposure, so a dollar-neutral long/short book at `invested=1` puts the whole
> book to work and still nets to zero; its cash is 1. A short-only book's cash exceeds 1, because
> selling short raises cash. Cash is always the NET residual, never `1 - invested`.

Their reading, and it is a fair one: *"A quantity that is explicitly not `1 - cash`, and whose
companion sentence points out that cash can exceed 1, does not read as capped at 1."*

## What happens

```json
{"code": "simulation.callback.intent.ValueError",
 "observed": "invested must be greater than zero and no greater than one",
 "requirement": "the guarded boundary must complete without raising",
 "example_total": 0, "examples": []}
```

`src/vqapr/authoring.py:670`, verified. No `fix`, no `explain`, no `source` — that half is
**016**.

## The consequence on the deliverable

`invested="1"` is 0.5 long / 0.5 short. Every number in the journey's REPORT.md therefore carries a
caveat: the factor return it measures is exactly half a textbook $1-long/$1-short SMB+HML, and the
headline must be doubled to be compared against anything published. The reporter's sentence is the
argument for treating this as more than a docs gap:

> If the cap is deliberate, then a gross-exposure parameter capped at 1 cannot express the standard
> scale of the thing the package ships `fama_french_cut_points` for.

That is a real tension with **021**: the package ships a validated Korean Fama-French replication
and its book-scale parameter cannot reach the scale the literature quotes those factors at.

## The question nobody could answer from the surface

Is the cap an invariant of the accounting, or a leftover from when the parameter meant `1 - cash`?
The reporter tried, in order: the `Rebalance.of` docstring (no bound mentioned), the `Budget`
docstring and its `cash_lower`/`cash_upper`/`target_lower`/`target_upper` fields (bounds exist as a
concept, none of them is `invested`), `vqapr run --help`, and the failure payload, which has no
`explain` topic to follow. The answer is marked unanswered in the log rather than guessed at.

**U-001 is what happened next**, and it belongs in this file because the gap that created it is this
one. The run wrote `.vqapr/diagnostics/<correlation_id>.txt` — a full traceback ending in

```
File ".venv\Lib\site-packages\vqapr\authoring.py", line 670, in of
    raise ValueError("invested must be greater than zero and no greater than one")
```

The package handed over the exact file and exact line that would answer the question, inside the
reporter's own project directory, produced for them to read. They wrote the urge entry instead of
opening it, took only the frame naming their own file, and left the question open. A traceback into
`site-packages` is a normal and useful thing for a diagnostics file to contain and should not be
removed. What it demonstrates is that the package's own failure artifact was the strongest pull
toward the source that the whole run produced, and the reason it had any pull at all is that
`explain` was absent.

## What closes it

**Decide the cap first, because the docs answer depends on it.**

- If `invested <= 1` is a genuine invariant: say so in the `Rebalance.of` docstring in the same
  breath as "GROSS exposure", and give the failure a `fix` naming the legal range. The
  long/short example in that docstring then needs a sentence saying that a textbook-scale factor
  book is expressed at half scale and doubled on the way out — because that is what a reader of
  `fama_french_cut_points` will need to do.
- If it is a leftover from a `1 - cash` reading: the cap should be the gross bound the docstring
  already describes, and a dollar-neutral book at `invested=2` should be legal.

Either way the failure needs an `explain` topic. That is the field whose absence sent a reader to
`site-packages`.
