# 010 — Two writers share one account table

**Status: CLOSED 2026-08-28** by `docs/implementations/066-the-account-table-carries-measurements-only.md`.
Effectively option 3, arrived at through option 1: the decision-time row moved to its own table
first, and that table was then removed after measurement showed it duplicated `vqapr.account`
offset by one commit, with no reader. `vqapr.account` carries measurements only. The sparse-valuation-clock row stayed, because removing it cost 8 of 10
measurements exactly as 056 recorded -- `test_valuation_clock.py` caught that on the first attempt.
No run's numbers moved; `show_005` is bit-identical across the change.

Found 2026-08-27 while diagnosing why `show_005` failed, by asking what wrote the 42
account-level rows a 21-occurrence run produced.
**Touches:** `src/vqapr/flow/simulation.py`, `showcases/show_005_enhanced_index/run.py`,
`docs/vqapr-architecture.md`

> **The valuation engine is correct and this issue does not propose changing it.** A standalone
> valuation marks at its own instant, a halted holding carries its previous price forward, and NAV
> values the whole held book. All three were verified against the code during this investigation.
> What is wrong is narrower: `vqapr.account` has two writers, and half its rows carry no nav.

## What happens

A run with a daily valuation clock and a daily decision clock writes **two** account-level rows per
occurrence. `show_005` over 21 callback days produces 42:

```
valuation occurrence  ->  21 rows,  nav present     the measurement
strategy callback     ->  21 rows,  nav = None      a restatement, suppressed
```

Measured directly:

```
ACCOUNT ROWS: 42
distinct observed_at: 22
nav None: 21
```

The callback row is not empty — it carries `cash` and `account_version`, so it does record the
account as the decision saw it. Only `nav` is `None`.

## Why the second writer exists

Before `docs/implementations/056`, `vqapr.account` was written **only** from the callback path;
056 records this in as many words: *"it was written only from the callback path."* A valuation
occurrence back then replayed the last committed mark instead of taking one, which produced the
defect 056 exists to remove — *"an independent valuation clock produced a NAV series that moved
only when a trade did."*

056 gave the valuation path its own mark and its own row, and left the callback row in place behind
a suppression guard. The guard sets `mark = None` and then **appends the row anyway**, so what is
suppressed is the number, not the record.

The guard is keyed on the identity of the mark rather than on whether a valuation agenda exists,
and that narrowing was measured rather than reasoned: the broad condition left *"only 2 of 10"*
measurements standing.

## Why it is worth fixing anyway

**The justification 056 gives for the callback row does not describe normal use.** It reads:

> the two cadences are independent session tuples, so a run may legitimately declare a valuation
> clock sparser than its decisions, and on a session that clock does not cover the replayed row is
> the only record there is.

That is true and it is backwards from the common case. The normal research shape is a valuation
clock **denser** than the decision clock — value daily, trade monthly. A valuation clock that fires
only when a decision does is precisely the defect 056 removed. Checked against the tree:

- nothing in `preflight.py`, `workspace.py` or `flow/run.py` constrains the relationship between
  the two clocks; only type and id agreement are enforced;
- all five in-tree showcases reuse `callback_days` verbatim for their valuation agenda, so **no
  run in this repository declares the sparse shape the row exists to serve.**

So on every run that exists today, the callback row is a guaranteed-`None` nav.

**One table, two meanings, and the reader has to know which.** A consumer reading `vqapr.account`
for a NAV series must filter `nav is not None`, and a consumer who forgets gets one real value
paired with one null per date. That is the exact shape 056 measured as HML correlation **0.9726 ->
0.6877** — *"not by moving a number, but by pairing each real return with a spurious zero one."*
The narrow guard suppressed that symptom; it did not remove the condition that produces it.

## Shape of the fix

**Separate the two facts rather than the two writers.** The callback row answers *"what did the
account look like when the decision was made"* — `cash`, `account_version`, positions. The
valuation row answers *"what was the book worth, and when was that measured"*. Those are different
questions and one of them is currently answered with a null column.

Options, in the order they should be argued:

1. **Give the callback row its own table.** `vqapr.account` becomes measurement-only, so every row
   in it carries a nav and no consumer needs a filter. The decision-time snapshot moves to a table
   whose name says that is what it is.
2. **Keep one table, add a discriminator column.** Cheaper, and it leaves the trap in place: a
   reader who does not group by the discriminator still sums a series that is half null.
3. **Drop the callback row.** Simplest, and it is what 056 explicitly declined after measuring the
   loss. It must not be reopened without a measurement that contradicts the one already recorded.

Option 1 is recommended. It is the only one where a naive read of the table cannot be wrong.

## What not to do

**Do not remove the suppression guard.** It is load-bearing and the number it protects is recorded:
the broad version cost 8 of 10 measurements. Whatever replaces the second writer must keep the
property the guard delivers, which is that one measurement is recorded once.

**Do not make the valuation clock depend on fill commit.** The independence is what makes valuation
run on days with no trade. Tying them would restore 056's defect exactly.

**Do not treat the `continue` branch in `valuation/marking.py` as the halt path.** By the time a
price is missing there, `_marks_from_execution_snapshot` has already tried to carry a previous mark
forward and found none — so that branch is a position the venue has *never* priced. A halted
holding keeps its last price, stays in NAV, and reports the instant that price was observed.

## To measure when this is picked up

- **The naive read is correct.** `SELECT sum(nav) ... GROUP BY date` over `vqapr.account`, with no
  filter, returns one value per date. Today it returns one real value and one null.
- **`show_005`'s assertion fails and says why.** It currently pins two account-level rows per
  occurrence, one measured and one restated, and names this issue. Resolving this should break that
  assertion — that is the point of it.
- **No run's numbers move.** This is a record-shape change, not an accounting one. Correlation and
  account version must be bit-identical across the change, the same adjudication 056 applied.
