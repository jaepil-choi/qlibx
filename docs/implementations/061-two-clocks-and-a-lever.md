# Two clocks and a lever

## Why this exists

Three separate things, all held together by `WORKSPACE_DIRECTORY` being a constant
(`workspace.py:47`) and `available_at` being stamped from one hardcoded column.

**The heavy artifacts had nowhere else to go.** A factor run produces roughly 500MB, and it landed
inside `.vqapr/` beside the catalog — a small file that wants to be version-controlled and backed
up. Two kinds of thing with opposite lifetimes, forced into one directory by one constant.

**Every published table was dated by the same column.** `publish_run_record` is generic over any
recorded table, and it stamped `available_at` from `event_time` for all of them.

**A dead loop was watching for something no gate could see.** `derived_available_at` searched its
accesses for an instant later than `evaluation_time`. Unreachable — every observation query binds
`available_at <= evaluation_time` (`scan.py:579,620`).

## `store`, defined once

`StoreSpec` (`flow/store_spec.py`) owns the keys, and it is the only thing that does. AC-P3 — an
empty `tables` leaves a run record and no dataset, a non-empty one makes each named table a dataset
— reads like a second rule and is really a consequence of the first, so it is asked through
`publishes_datasets` rather than re-derived at each call site. The test imports `StoreSpec` and
compares its dataclass fields against `STORE_KEYS`, so a key added in one place and forgotten in
the other is a failure rather than a drift.

That is AC-X4′, which replaced the original "a grep finds no second normative definition" —
ungreppable, because *normative* is a judgment and grep returns textual hits either way.

A relative `store.root` resolves against the spec's own directory, not the process's working
directory. The alternative makes one spec mean different things depending on where it was run
from, which surfaces the first time somebody runs it from somewhere else and looks like data loss.

## Two clocks, and why the column cannot be hardcoded

`RunRecordSpec` now declares which column says when its rows became knowable.

`observed_at` is a **measurement** clock — when the value was seen. `vqapr.account` declares it,
because a NAV is a measurement of a book at an instant. Dating that series by `event_time` labels
every value by when the row was *written*, and since the record trails the callback that writes it,
every value lands one occurrence late. Measured, that mislabelling took a factor correlation from
**0.929 to 0.017** (F-009). Nothing raised; the series was simply wrong.

`event_time` is a **decision** clock — when the row happened. `allocation` and `vqapr.weight`
declare no `observed_at` at all, because the row *is* the decision; there is nothing separate to
have observed.

So a package-wide column is right for one table and silently wrong for the next — silently, because
both produce a plausible date. The field is per table, it must name a column the record actually
carries, and a row missing its declared clock is refused rather than quietly stamped with the other
one. A substituted date is a wrong date that looks right.

Mutation-proved: reverting to the hardcoded `event_time` fails the account test.

## The dead loop became the assertion

Deleting unreachable code is normally right. Here it would have removed the only thing watching for
a failure nothing else can see.

**Look-ahead improves correlations.** A run that reads tomorrow's price produces *better* numbers,
so the count gate passes, `compare_factors.py` passes, and every downstream figure looks like an
improvement. A silent improvement is the hardest kind of wrong to notice, and the loop's
reachability was contingent on a bound in a different module that a future change could loosen.

The branch is gone; the invariant it depended on is now checked. `LookAheadDetected` names the
dataset, the bound that was supposed to prevent it, and why no other gate would have caught it.

This surfaced a test that was asserting the opposite contract. It fed a read from two hours *after*
the cutoff and asserted the stamp followed it forward — an input the PIT bound cannot produce. That
test would have passed on a package that leaks, which is the direction that matters. It now checks
the real property forward and the look-ahead refusal separately.

## Re-publication

`materialize` refuses an existing `dataset_id`. The refusal now names the exact `--force` command
instead of only saying the id must be new. Refusing by default is the right way round: in a
five-process factor loop a repeated run to the same result name is far more often a retry than an
intended overwrite, and an accidental clobber is unrecoverable while a refusal costs one flag.

## Validation

```
uv run --no-sync pytest -q                                   # 1,186 passed
uv run --no-sync ruff check .                                # clean
python ../kwam-enhanced-index/vqapr-testbed-2/parity_probe.py --factors HML
```

Count gate MATCH: 2096 / 97 / 110919. Value gate exact, weight digests byte-identical to the Step 0
capture. This is the highest-sensitivity step after Step 1 — it changes the availability-stamping
clock that produced F-009 — so both gates were mandatory rather than tiered.

Both mutation tests fire: the hardcoded `event_time` clock fails the account test, and the old
silent-stamp loop fails the look-ahead test.
