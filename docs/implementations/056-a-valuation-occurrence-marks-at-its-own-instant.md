# A valuation occurrence marks at its own instant

## Why this exists

A run values its book where the venue published a price, and the venue publishes one every
session. But `_dispatch_valuation` did not value anything: it replayed whatever mark the Account
had last committed.

```python
marks = self._committed_marks(state)
```

The consequence is that the NAV series silently inherited the **decision** cadence. A strategy
that rebalances monthly reported a monthly NAV even though its book was worth something, and
knowably so, on every session in between. Factor research measures return from that series, so a
strategy's rebalance rule was quietly deciding how often its own performance could be observed.

The framework's own testbed had already worked around this without naming it. Its factor build
declares a **daily** strategy agenda with a monthly rebalance rule, and the model's docstring
explains why: "a monthly agenda would produce a monthly NAV series; a daily agenda with a monthly
rebalance rule produces the daily series a factor return is measured from." That is a workaround
for this defect written in the voice of a design decision.

## What changed

A standalone valuation now marks synchronously, at an instant it resolves for itself, and records
what it measured.

**The instant.** `ExecutionHorizon.at_or_before` is new, and it is deliberately not the mirror of
the existing `after`:

```python
index = bisect_right(self._instants, instant.astimezone(UTC))
return self._instants[index - 1] if index else None
```

`select_target` selects the first **strictly-later** eligible instant, which is correct for an
intent — a decision cannot fill in a print that already happened — and wrong by exactly one
instant for a valuation. On the shipped cadence (decide 08:00, fill 15:30, value 16:00) a
strictly-later rule binds *tomorrow's* fill, stamping NAV one execution instant late along its
entire length. `None` is a real answer: the venue published nothing at or before this moment, so
no value exists, which is different from the value being zero.

**The occupancy.** `pending_accepted_intent` holds a **single** occupant. Routing a daily
valuation through it would evict accepted decisions on most sessions. The chosen mechanism never
touches the slot, and `prepare_standalone_valuation` is its lifecycle: unlike the neighbouring
`prepare_valuation_only`, it consumes no pending identity, because a standalone valuation never
minted one.

**The record.** Marking alone would have left the change invisible. `vqapr.account` is what a
later reader reconstructs the series from, and it was written only from the callback path. The
valuation now writes its own row, and the callback skips the replayed one when — and only when —
a valuation already recorded that exact measurement.

**The identity.** The pending uuid5 key was `run_identity|instant`, carrying no role, so two
occurrences at one instant minted the same id. `pending_id` is the token proving a completion
matches its own preparation, so a collision degraded that invariant to a coincidence. The key
now carries the role.

## Two defects found while building it

**Duplicate rows.** With both clocks daily, the callback's replayed row and the valuation's own
row are two records of one measurement. A reader dating the series by the measurement then finds
two rows per date and pairs every real return with a spurious zero. Measured on the factor
testbed, that took HML's correlation against its published reference from **0.9726 to 0.6877**.

**The skip was too broad.** The first fix keyed the skip on whether a valuation agenda *existed*.
The two cadences are independent session tuples, so a run may legitimately declare a valuation
clock sparser than its decisions, and on a session that clock does not cover the replayed row is
the only record there is. Measured with the broad condition, only **2 of 10** measurements
survived. The skip is now keyed on the identity of the mark.

## Trade-off

The run-state version now advances on every recorded valuation: the sample journey moved from
2,929 to 3,664. The **Account** version is unchanged at 729, which is the number that matters —
a mark without a fill values the book, it does not trade it. Both were previously reported under
the single name `account_version`, which made this look like an accounting change; they are now
two fields, `run_state_version` and `account_version`.

`show_007` grouped rehydrated marks by account version alone. That assumption was true only while
every mark came from a commit, and it now groups by `(version, event_time)`.

Not attempted here: a valuation whose instant coincides with a fill still records no row, because
the fill already marked at that instant and mark history must be strictly increasing. That case
is filed rather than fixed.

## Validation

```
uv run --no-sync pytest -q                                   # 1,065 passed
uv run --no-sync ruff check .                                # clean
python ../kwam-enhanced-index/vqapr-testbed-2/parity_probe.py --factors HML
```

Count gate MATCH: callback_days 2096, formations 97, membership_rows 110919.

Value gate exact: all 97 HML formations reproduce the committed baseline weight values, digests
byte-identical to the pre-change capture.

**Correlation adjudication.** The new NAV series truncated to the old series' last date gives
`0.972553170141279` over the same 1,973 days — bit-identical to the pre-change figure, with zero
shared dates showing any differing return. The full series differs by exactly one additional
session, 2026-07-20, the venue's final print, which the old code structurally dropped because no
later callback existed to replay its mark.

Every test in `tests/flow/test_valuation_clock.py` was confirmed to **fail** against the original
code and pass against the change, so "the absence of a change" — the failure mode this step could
most easily have shipped — is ruled out by measurement rather than by assertion.
