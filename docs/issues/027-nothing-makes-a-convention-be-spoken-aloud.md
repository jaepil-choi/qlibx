# 027 — Nothing in the tooling makes a point-in-time convention be spoken aloud

**Status when filed:** open, and **it is a proposal rather than a defect**. Found 2026-08-30 by the
final first-time-user journey in `kwam-enhanced-index/vqapr-final-testbed/`, against
`vqapr-0.2.0a1`. Recorded there as **P-001** and marked *"Attributable to vqapr? **No**"* — it is
the agent's own process failure, and the user had to catch it. This file exists only for the one
paragraph the reporter flagged as worth reporting upward anyway.
**Touches:** `vqapr register`'s success envelope; the skill's `available_at` section.

## What the agent did wrong, in its own words

It asked the user about **one** convention — when a December book-equity figure could first have
been known — and decided five more alone:

| decision | what it chose |
|---|---|
| daily close `available_at` | 15:30 KST, the session close |
| formation stamp `available_at` | last June session 15:30; monthly stamps at month-end 15:30 |
| execution `trade_at` | 15:30, `selector: same_day`, `trade_price: close` |
| price adjustment | back-adjusted for trading, **raw** for market equity |
| `is_tradable` | trading-halt flag == 0 AND volume > 0 |
| valuation instant | 15:31, after the fill |

The skill told it not to. It quotes the two sentences it read and then did not apply outside the
accounting data:

> The framework validates schema, keys and duplicates. It cannot detect a look-ahead, because a
> timestamp that is wrong in meaning is still perfectly well-formed.

> Ask, and do not answer on the user's behalf ... **Do not infer a convention from a column name.**

The worst of the six is the price adjustment, because it is not one convention: the pipeline trades
a back-adjusted series and ranks on the raw close. Both are defensible alone; the pair was never put
to the user as a pair.

**The skill is not at fault and this file does not claim otherwise.** The execution-input template
even comments its `at:` and `selector:` fields, so the surface prompted at the exact moment
`trade_at` was decided unilaterally.

## The upward-reportable part

> the framework accepted all six without a word.

`register` validated the dataset and the execution input, `check` passed five phases and eight
judgments, and `run` completed — with a `trade_at` invented, an `available_at` inferred, and two
different price series in the same run. That is the designed behaviour and the skill says so
plainly. What the reporter observes is that **the skill's answer to this is a paragraph an agent can
read and then not act on**, and that nothing in the tooling creates a moment where these decisions
have to be spoken aloud.

Their proposal, quoted because it is small and specific:

> A `vqapr register` that echoed back "you have declared that this column means X was knowable at
> 15:30 Asia/Seoul" would have made me look at it once more.

## Why this is worth a decision rather than a dismissal

The failure mode is the one the whole PIT design exists to prevent, and it is the one class of
error the package has already conceded it cannot detect. A restatement is not detection — it cannot
tell a right convention from a wrong one — but it is the only mechanism available that costs
nothing and lands at the moment the claim is made rather than in a paragraph read an hour earlier.

Note that it composes with **015**. There, a look-ahead the framework *can* detect went unreported
because `run` does not ask. Here, a look-ahead the framework *cannot* detect went unspoken because
nothing asks the user. The two together are why this journey's numbers were provisional until the
six conventions were confirmed afterward.

## What to settle

Whether `register`'s success envelope restates the meaning of what was just declared — in words, not
as an echo of the YAML — for the fields where meaning is the whole content: `available_at`,
`trade_at`, `at`, `timezone`, `selector`, `trade_price`.

**The failure mode to avoid** is a restatement so verbose it is scrolled past, which turns it back
into the paragraph it was meant to improve on. One sentence per PIT-bearing field, or nothing.
