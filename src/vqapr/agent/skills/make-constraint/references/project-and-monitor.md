# `project` and `monitor` — two questions, not two halves of one

## The distinction

| | asks | when | nature |
|---|---|---|---|
| `project` | what is the best portfolio I can build inside this limit? | decision time | **best effort** |
| `monitor` | did what I actually hold exceed this limit? | after each commit | **observation of fact** |

They are not the before and after of a single question. Construction may legitimately produce
something the signal did not want — that is what a limit is for. Monitoring does not care how hard
construction tried.

## `project` returns the box

The **lower and upper weight bound for every instrument**. Not the offenders, not a correction, not
a modified portfolio.

The optimiser needs a feasible region, and a region is what makes the result reproducible: two runs
of the same declaration produce the same box, and what happens inside it is the strategy's.

Returning "the names that broke the rule" instead would put the constraint in the business of
deciding what to do about them, which is the strategy's judgement.

## `monitor` looks from outside

It receives the **marked account** — what is actually held, after fills — and returns a
`ConstraintFinding` carrying the bound and the measured value.

Note the timing: monitoring runs on the **committed** state after each commit, on its own cadence.
That is a different instant from the decision, and a book can be inside the box at decision time
and outside it after the fills. Both facts are true and both are recorded.

## Effort is not scored twice

If a decision went outside the limit, that is a violation, and monitoring catches it.

Scoring construction separately for "did it try hard enough" would give two verdicts on one
decision, and when they disagree there is no way to say which is the fact about that strategy. So
there is one verdict, and it comes from what was held.

## Execution does not evaluate constraints

Evaluating a limit is an economic judgement; execution's job is to fill what has already been
decided. A constraint never causes a fill to be rejected — it shapes the target beforehand, and it
observes the outcome afterwards.

## What lands in the record

`vqapr.monitoring`, one row per constraint per commit: `constraint`, `passed` (your own
comparison), `measured`, `bound`, `excess`, `verdict` (the framework's), `tolerance`, `offenders`,
`account_version`. `event_time` is the fill instant the book was committed and judged at.

The strategy record's `contract` block only carries counts. **Which name breached which limit by
how much is in the table**, so a compliance question goes there.

## An empty monitoring table

Means the constraint was never evaluated — not that it was never breached. Say which when
reporting. A constraint that failed to get its data, or that was never named by the strategy, is
silent in exactly the same way as one that held perfectly.
