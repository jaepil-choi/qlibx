# 066 — The account table carries measurements only

Issue 010. `vqapr.account` had two writers and half its rows carried no nav.

## What was wrong

A run with a daily valuation clock and a daily decision clock wrote two account-level rows per
occurrence:

```
valuation occurrence  ->  21 rows,  nav present     the measurement
strategy callback     ->  21 rows,  nav = None      a restatement, suppressed
```

The suppression guard `056` added set `mark = None` and then appended the row anyway, so what it
suppressed was the **number**, not the record. A consumer reading a NAV series had to know to
filter `nav is not None`, and one who forgot paired every real value with a null — which is the
exact shape 056 itself measured as HML correlation **0.9726 → 0.6877**, *"not by moving a number,
but by pairing each real return with a spurious zero one."* The narrow guard suppressed that
symptom without removing the condition that produced it.

The row was not empty: it carried `cash` and `account_version`, so it did record something real.
That is the point — **two different facts shared one table, and one of them answered with a null
column.**

## What changed

**`vqapr.account` carries measurements only.** The row a callback wrote when a valuation had
already recorded that measurement is gone. It held `nav=None` and competed with a real value in
the same table, which is the null-pairing 056 measured.

**The property `056` bought is kept.** A valuation clock sparser than the decision clock leaves
sessions its own occurrences never reach, and on those the mark a callback replays is the only
record of the book's value there is. That row still goes to `vqapr.account`, because it is a
genuine measurement nobody else will write. What is gone is the row written when a valuation
**already** recorded that measurement.

**The dedup key moved to the measurement instant.** `_recorded_measurements` holds the instants a
mark was *taken*, not the occurrences that wrote them, because a callback replays a committed mark
and the two clocks differ — comparing occurrences would never match and the duplicate would go out
under a later `available_at`.

## The second table, and why it did not survive

The first version of this change moved the callback's decision-time facts into a new
`vqapr.decision_account`, on the argument that "what did the account look like when the decision
was made" is a different question from "what was the book worth".

Measured against the run, it was not a different question. Matched on `account_version`, its rows
were **identical to `vqapr.account`'s on every version the two shared** — the same series offset by
one commit, because a callback reports the account it saw and a valuation reports the account it
valued. Its only genuinely unique row was version 0, the initial account, which
`FrozenRun.initial_account_snapshot` already carries. Nothing read it.

So it was removed under this package's own rule: *machinery whose only user is its own test is not
a feature*. Recording the argument here because the argument sounded right and the measurement
disagreed; if a decision-time account series is ever wanted, it should be designed alongside the
consumer that wants it, which will also say whether it needs to be a table at all.

## What this cost, and what it did not

I removed the callback's account row outright first. `test_valuation_clock.py` caught it
immediately: *"measurements were lost on sessions the valuation clock did not cover: only
['2024-03-06', '2024-03-13']"* — 2 of 10, which is precisely the loss 056 recorded when it tried
the broad condition. The issue had said so in as many words (*"whatever replaces the second writer
must keep the property the guard delivers"*), and the test proved it rather than the note.

That is why the row survives for the sparse case. The fix is narrower than "delete the second
writer" and had to be.

## Validation

- `uv run pytest tests/` — **1,306 passed**, including
  `test_a_sparser_valuation_clock_still_leaves_every_callback_session_valued`, which is the
  measurement 056 recorded and the one this change could most easily have broken.
- All seven runnable showcases pass.
- **The naive read is correct.** Measured on `show_005`: `vqapr.account` holds 21 account-level
  rows, **all 21 carrying a nav**, across 21 distinct dates — one value per date, no filter. It
  was 42 rows with 21 nulls.
- **The package still owns exactly three default tables**, pinned by
  `tests/flow/test_account_table_is_measurement_only.py`.
- **No run's numbers moved.** `show_005` against this change and against `HEAD` is bit-identical:
  commission `225511.46100000`, sale tax `264798.6000000`, final NAV `1169325979.93900000`, active
  weight L2 `0.01065555767675562865938491427`. This is a record-shape change, not an accounting
  one — the same adjudication 056 applied.
- `show_005`'s assertion was written to fail here and did. It pinned two account rows per
  occurrence and named this issue; it now pins one, plus the absence of any null nav.
