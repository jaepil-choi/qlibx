# The book is valued where it is executed

## Why this exists

Valuation used to subscribe to the observation dataset through `valuation.mark_requirement`, on a
`valuation_agenda` independent of execution. Marking one holding meant asking "what is the newest
row at or before this cutoff", which has no SQL lower bound and therefore scans from the start of
the dataset — for every held name, on every valuation, forever.

That was the most expensive query shape left in the hot path. But the reason to remove it is not
that it was slow.

**A run had two answers for what its own book was worth.** It filled at the venue's executable
price and then marked at the observation close. Those are different numbers from different tables,
and the one it marked with is the one it could not have traded at.

Now there is one source. The prices the venue published as executable at the execution instant are
the prices the book is valued at, because the run is already reading them to fill against.

## What changed

### 1. A `NoDecision` occurrence reaches the execution instant

`_pending_due` returned `None` when nothing was pending, so a declining callback never reached the
venue at all. It now takes a `PendingValuation`: an occurrence bound to a selected target, with no
intent.

**An empty `EconomicPortfolioIntent` could not be reused for this.** Two independent contracts turn
"hold" into "liquidate":

- `validate_economic_intent` requires `cash_target == 1` for an empty target set — everything in
  cash.
- `plan_orders` gives any held instrument absent from `weights` a `desired` of zero — sell it all.

So the valuation path reaches the snapshot without passing through `plan_orders` or
`Exchange.execute`.

**A `NoDecision` only takes a pending when none exists.** The first wiring of this overwrote a
waiting accepted intent, which silently discarded a decision the Strategy had already made and a
fill that was going to happen. `tests/acceptance/test_time_002.py::test_no_decision_preserves_existing_pending_until_due`
caught it. `_accept_valuation` now declines in three cases: an intent is already pending (its own
due execution values the book), the run declared no execution authority (a research run that only
exercises callbacks), or no execution instant remains in the horizon.

### 2. Marks come from the execution snapshot

`exact_execution_snapshot` already requests `(*target, *held)` and already reports
`missing_held_instruments`. The data was being fetched and thrown away.

`_marks_from_execution_snapshot` reads it:

| snapshot says | mark |
|---|---|
| row with a price, `is_tradable=true` | that price, `observed_at` = execution instant |
| row with a price, `is_tradable=false` | **that price**, `observed_at` = execution instant |
| no row, or no price | **carry the previous mark, keeping its original `observed_at`** |
| no row and no previous mark | none; left out of NAV, quantity stays in the account |

`is_tradable=false` still marks, because refusing to trade and refusing to quote are different
facts. The venue published a price; that is the best statement of what the holding is worth, even
though it cannot be sold at that instant.

**Carry-forward is the part this design turns on.** Without it a halted name would drop out of NAV
entirely and the denominator every later weight is converted against would silently shrink. And the
carried mark must keep the instant its price was *observed*, not the instant it was carried —
otherwise a name halted for a year looks freshly priced at every occurrence and the halt is
invisible in the evidence.

### 3. Valuation and monitoring occurrences read the committed mark

`_dispatch_valuation` and `_dispatch_monitoring` used to derive a fresh valuation. They now read
`AccountState.latest_mark`. Monitoring judges the account the run actually committed; deriving a
second valuation from a different price source is how one run ends up with two answers.

Between execution instants nothing about the valuation can have changed, because no new price has
been published to change it.

### 4. A mark is identified by when it was taken

`mark_history` required strictly increasing `account_version`. That was only true while every
valuation followed a fill. An occurrence that trades nothing values the book without advancing the
version, so one version now carries several marks.

`AccountMark` gains `marked_at` and `observed_at_by_instrument`. Ordering moved from version to
instant: versions must not decrease, instants must strictly increase. "A mark for an earlier
version arriving later" is still refused.

`Account.prepare_valuation` / `commit_valuation` publish a mark-only transition —
`PreparedAccountValuation` proves snapshot, version and fill history are unchanged. A zero-fill
transition was considered and rejected: a version bump with an empty journal would make
`account_version` stop meaning "the account changed", which is exactly what the optimistic
concurrency checks in `venue.py:74`, `simulation.py` intent authority and monitoring rely on.

### 5. An unpriced holding is unvalued, not fatal

Two places refused:

- `ValuationService.mark` raised `missing selected mark for ...`
- `Account.prepare_mark` required marks to *exactly cover* positions

Both are relaxed. `_require_marks_within` now enforces a subset: marks may not contain instruments
the account does not hold, and must value the held quantity, but need not cover everything.

This restores a position record 020 already took for the execution path — *"NAV values what can be
priced at this instant; an unpriceable holding contributes nothing to the denominator rather than
being priced from a stale quote"* — to the valuation path, which had never followed.

### 6. `mark_requirement` and the valuation subscription are gone

`ValuationConfig` keeps only its agenda. Removed: the field itself, `public._marks_for_occurrence`
(44 lines, fully dead once the three call sites moved), the
`SimulationFlow(marks_for_occurrence=...)` constructor argument, the preflight valuation
requirement, the workspace mark-dataset registration check, and the four `mark_requirement` entries
in the frozen-run identity digest.

**A stored `mark_requirement` is refused, not ignored.** A workspace or CLI document written before
this change declares a price subscription the run would silently not use, and its NAV would differ
from what that declaration says it should be:

```
valuation config 'x' declares mark_requirement, which no longer exists:
valuation reads the execution table, so re-register the valuation config without it
```

## Trade-offs

**A run cannot value its book more often than it makes decisions.** Daily NAV requires daily
callbacks. `NoDecision` returns immediately, so this is a scheduling constraint rather than a cost
one, but it is real and now stated in canon §3.6.

**Valuation inherits the execution table's coverage.** If that table carries rows only for instants
the venue traded, the book is marked only at those instants. For a daily close-priced run this is
identical to before; for a sparser execution table it is not.

**Marking at the executable price changes what NAV means.** A book valued at the close and traded
at the open was marked at a price the run could not have realised. This is the intended correction,
and it will move results wherever the two tables disagree.

## Validation

```
uv run pytest -q      527 passed   (523 before, +4 from the rewritten stale-mark suite)
uv run ruff check     clean
```

`tests/valuation/test_stale_marks.py` was rewritten rather than deleted. The contract it protected
still holds; only the mechanism moved. It now pins carry-forward directly, including the two cases
that are easiest to get wrong: a carried mark must not restamp its `observed_at`, and a sold
holding must not be carried back into the book by an older mark that mentioned it.

The new path was verified to actually run rather than inferred from an unchanged result:

```
_marks_from_execution_snapshot     84 calls, 336 marks
_marks_for_occurrence (old path)   168 -> 0
observation queries                504 -> 252
```

Carry-forward proved directly, since show_005 never halts a name across an execution instant:

```
mark 1  nav=100.0  marked_at=03-05   A: price=10.0  observed_at=03-05
mark 2  nav=100.0  marked_at=03-06   A: price=10.0  observed_at=03-05
```

The venue published nothing for A on 03-06. NAV held at 100 instead of shrinking, and `observed_at`
stayed at 03-05 so `staleness()` reports the real gap.

A `NoDecision` occurrence proved to value the book without advancing the version:

```
lifecycle: ACCEPTED_INTENT -> ACCOUNT_COMMITTED -> MARKED -> FEEDBACK_PUBLISHED
           -> NO_DECISION -> MARKED
account version : 1
marks           : version=1 nav=100.0 prices={'A':'10'}
                  version=1 nav=250.0 prices={'A':'25.0'}  marked_at=03-06
```

No trade happened between those two marks. NAV moved because the price did.

### Result invariance

`showcases/show_005_enhanced_index`, against the snapshot taken before any of this work:

```
63 of 64 fields identical
drifted: artifacts.alpha_allocation.lineage.json
```

`alpha_allocation.parquet` digest, final NAV, committed cash, replayed positions and dealt fills are
unchanged. **No data moved.** The lineage file changed because frozen-run identity no longer
contains `mark_requirement` — the declaration genuinely disappeared, so the provenance record has to
say so.

That the numbers did not move is a fact about this fixture, not a general guarantee: its execution
table and observation table carry the same close at the same instant, so both price sources agree.
Where they disagree, results will differ, and that is the point of the change.
