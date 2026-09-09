---
name: make-constraint
description: Writes and validates a vqapr Constraint — position limits, sector caps, turnover budgets, and compliance rules, in either adjusting or reporting mode. Use when the user wants to cap, limit, or restrict a portfolio; mentions a mandate, guideline, risk limit, or compliance rule; or asks why a constraint reported a breach instead of changing the portfolio.
---

# Write a vqapr Constraint

## Invoke the CLI through the active environment

Installing a console script into a virtual environment does not put it on the global shell PATH.
Use one launcher consistently:

- activated environment: `vqapr --help`
- uv-managed project: `uv run vqapr --help`

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed; the environment
is simply not activated. Apply the same prefix to every command below.

## Constraints are optional

Not a precondition for research. Only a workflow that chose constraint adjustment or actual-account
monitoring has to supply a metric, a bound, an evaluation scope and the data behind them.

A strategy names its constraints in a `constraints:` list under the run's `strategy:` block,
pointing at registered components of kind `constraint`.

## Start from the scaffold

```bash
vqapr new constraint <id> --cap 0.2
```

writes a single-name position cap that registers and runs unedited.

## One declaration, two consumers, two different questions

This is the thing to understand before writing either method.

```
declaration ──► bound at decision time     (construction)  — best effort inside the limit
declaration ──► verdict on committed state (monitoring)    — did the book actually exceed it
```

**These are not the before and after of one question.** Construction asks *what is the best I can
do inside this limit* and is best-effort — when the portfolio the signal wants and the portfolio
the limit allows differ, it builds the second. Monitoring asks *did what I actually hold exceed the
limit* and is an observation of fact — regardless of effort, over is over.

| method | returns | consumer |
|---|---|---|
| `project` | the lower **and** upper weight bound for **every** instrument — the box the optimiser must stay inside | construction |
| `monitor` | a `ConstraintFinding` with the bound and the measured value, looking at the marked account from outside | monitoring |

`project` returns **the box, not the offenders and not a correction.**

**Construction is not separately scored for effort.** If a decision went outside the limit that is
a violation, and monitoring catches it. Scoring the same decision twice risks two verdicts that
disagree, with no way to say which is the fact about that strategy.

[references/project-and-monitor.md](references/project-and-monitor.md).

## Compare strictly; the framework applies the tolerance

A book executes in whole lots and is marked after its fills, so a realised weight lands a little
off the target. **Write the strict comparison** and let the framework judge the excess against
`max(bound × 1%, 10bp of NAV)` — once, in one place — and file it as `held`, `within_tolerance` or
`breached`.

Only `breached` makes the contract `ok: false`, and all three counts are reported so nothing is
hidden.

Override the line with a `tolerance` property returning a `Decimal` share of NAV. `None`, the
default, keeps the framework's. [references/tolerance.md](references/tolerance.md).

## A constraint declares the data it needs

And **fails before producing a result** if that data is absent. A missing input is never read as
"within limits".

The declaration must be **a thing with an identity**, not a bare pair of numbers, because the
result has to say which constraint compared which value against which bound and by how much it
was exceeded.

[references/declaring-data.md](references/declaring-data.md) also covers where a periodic constant
belongs — a fixed value for a period is published by a DataModel and subscribed to here, not
frozen into the constraint's source.

## A breach never stops a run

It is recorded. `vqapr show strategy` reports it under `contract`, and `vqapr.monitoring` holds one
row per constraint per commit: which rule, what the bound was, what was measured, and who
offended.

That triple — **which rule, what was the limit, what was it actually** — is deliberately all that a
violation record requires. Demanding more makes observation heavy, and heavy observation cannot run
often, so it ends up running less.

## Two built-ins, and what they will not assume

`w_i(t) ≥ 0` (no short), and `w_i(t) ≤ max(10%, w_i^index(t))`.

The second subscribes to **time-varying point-in-time** benchmark constituent weights. A name
**confirmed** to be outside the benchmark has `w_i^index(t) = 0` — but if the membership or the
weight data is **missing**, the evaluation fails rather than assuming zero.

Sector, turnover, liquidity, leverage and gross/net exposure policies are not shipped. Writing one
yourself is not blocked, as long as it fits the contract above: declare the data, project the
bound, measure the value.

## Validate before you believe it

```bash
vqapr register constraint <id> <file.py>
vqapr check <run-id>
```

A component that imports and loads is not thereby compatible. If a declaration has drifted far
from the contract, generate a fresh one with `vqapr new` and move your rule in.

## Stop condition

`vqapr check <run-id>` returns `ok: true`, and after a run `vqapr.monitoring` holds rows for this
constraint — an empty table means it was never evaluated, which is not the same as never breached.

---

A refusal carries its own status, stage and cause, plus `fix`, `requirement`, `observed` and
`source` — read it rather than looking for it here. Status **500 or 502 is a vqapr defect**: do not
work around it, report it with the envelope.
