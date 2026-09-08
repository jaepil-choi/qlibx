# `available_at` — what to ask, and why the answer decides everything

## Contents

- What the column means
- The three questions
- Worked cases
- Why vqapr cannot check this for you
- What to do when the answer is not known

## What the column means

`available_at` is **when the row could first have been known** — not when the event it describes
happened. Those two differ, and the gap between them is where look-ahead enters.

The framework validates that the column exists, that it is timezone-aware, and that the key is
unique. It cannot validate the meaning, because a timestamp that is wrong in meaning is still
perfectly well-formed.

## The three questions

Ask these. Do not answer them on the user's behalf.

1. **Is this column an observation, a publication, or a revision?**
2. **What timezone is the timestamp in, and is it an event instant or a date?**
3. **If it is a date, what instant within that date is defensible?**

Question 3 is the one that gets skipped. A date column widened to midnight says a daily close was
knowable fourteen hours before the market produced it. The profiler reports the wall clocks a
column actually lands on, so `wall_clocks ['00:00:00']` on a column of daily bars is the signal to
ask — the value is a stamped date, not an observed instant.

## Worked cases

**A daily close.** Available at that session's close in the venue's timezone. Not at midnight of
the same date, and not at midnight of the next.

**An accounting fact for a fiscal quarter.** Available when it was *published*, which is weeks or
months after the period it covers. A fixed lag applied to the period end is an approximation, and
whether it is a safe one is a judgement about the data — the filing calendar, the market, the
vendor — not about vqapr. If the user chooses a fixed lag, that choice belongs in the result's
limitations.

**A revised or restated value.** Available at the revision, not at the original observation. If the
source carries only the latest value for each period, then the file has no way to express what was
known at the time, and the user needs to hear that plainly: the dataset can be registered, and
every backtest over it will read revisions that had not happened yet.

**A signal the user computed themselves.** Available when every input to it was available — the
latest of them, not the earliest.

## Why vqapr cannot check this for you

Every check the package could apply passes on a wrong answer:

- a close stamped at midnight is a valid timezone-aware timestamp
- a fiscal fact stamped at period end is unique on its key
- a restated value is a finite number in a `DOUBLE` column

There is no version of these that fails. That is why the decision is raised **before** the first
`register`, and why a registration built on a guess is worse than no registration: it produces
results that look correct.

## What to do when the answer is not known

Say it is unknown, name what would settle it (the vendor's documentation, the collection process,
a colleague who built the extract), and let the user decide. Do not infer a convention from a
column name — a column called `date` proves nothing about availability.

If the user chooses to proceed on an assumption, that is their call to make. Record the assumption
where it will be read again: it changes what every result over this dataset means.

## Related

- [timezone-proof.md](timezone-proof.md) — naming the right zone is not the same as holding the
  right instant
- [discouraged-preparation.md](discouraged-preparation.md) — calculations that make a past row
  depend on a future observation
