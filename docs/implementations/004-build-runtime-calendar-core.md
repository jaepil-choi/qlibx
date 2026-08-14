# Build runtime calendar core

## Why this change exists

The package could register daily data but had no executable representation of venue sessions or
event time. All five files named by architecture rewrite-order step 1 were empty. Any later trigger,
materialization, execution, or PIT resolver would therefore have been forced either to infer cadence
from data coverage or to introduce its own clock and ordering rules.

That would violate three canonical boundaries:

- session time belongs to a frozen `SessionCalendar` and is not guessed from price coverage;
- event time exists independently of data rows;
- `DATA_AVAILABLE` is an inclusive resolver predicate, not an emitted event.

## Outcome

The runtime foundation now provides:

- timezone-aware validation, explicit local-time construction, DST gap/fold rejection, and calendar
  arithmetic with month-end clamping in `domain/timestamps.py`;
- a frozen `SessionCalendar` containing sorted unique dates, an IANA timezone, required session
  close, and optional explicitly declared session open;
- a closed calendar-derivation rule vocabulary and a pure `derive_calendar()` that accepts dates,
  records the selected rule, and returns machine-readable economic limitations;
- six real `EventKind` values with one fixed priority; and
- a frozen `Timeline` that deterministically sorts supplied events and has no clock or cursor.

`runtime/` does not import `data/`. Reading rule-selected dates from a registered dataset remains
rewrite step 2; model trigger policies and exchange fill conventions remain their owning later
slices.

## Responsibility and flow

```text
data layer later selects distinct dates under the user's declared rule
  -> derive_calendar(dates, rule, explicit session time)
  -> CalendarDerivationResult(rule + limitation + frozen SessionCalendar)

model/exchange declarations later produce Event values
  -> Timeline.of(events)
  -> frozen sequence sorted by timestamp then fixed EventKind priority
```

Calendar derivation deliberately receives only dates. It does not receive a source path, scan a
dataset, or choose a rule. The union/reference/index distinction is preserved as frozen input and
limitation evidence while the data-layer integration remains responsible for selecting the dates
that correspond to that declaration.

## Alternatives and trade-offs

- **Derive sessions automatically from price coverage** was rejected because it turns a venue fact
  into an unrecorded data-dependent guess.
- **Make `DATA_AVAILABLE` an event** was rejected because no runtime actor emits it. Visibility is
  the later Store predicate `available_at <= event.ts`.
- **Add trigger and fill declarations to Timeline now** was deferred because cadence belongs to
  Model and execution time belongs to Exchange. The Timeline remains ignorant of both meanings.
- **Require a session open for every close-based calendar** was rejected. An absent open is retained
  as unknown rather than invented; close remains required by the current daily-close scenario.
- **Resolve ambiguous DST wall times with a default fold** was rejected because either fold changes
  event time. A policy-less choice would make an economically relevant timestamp implicit.

## Evidence and validation

Regression tests were written first. They initially failed at import because all target modules
were empty. After implementation, the focused contract suite reported:

```text
uv run pytest tests/domain/test_timestamps.py tests/runtime tests/boundaries/test_runtime.py -q
-> 24 passed in 0.06s

uv run python scripts/evidence_calendar.py
-> union calendar sessions: 2024-03-05, 2024-03-06, 2024-03-07
-> same dates in a different order produced an equal result
-> reference-instrument result omitted 2024-03-06 and recorded reference-missing-removes-session
-> 04:00 DECISION existed without data rows
-> DATA_AVAILABLE was absent from EventKind
-> equal-time events were EXECUTION, FILL_COMMIT, VALUATION, MONITORING, FINALIZE

uv run pytest -q
-> 94 passed in 1.21s

uv run ruff check src tests scripts
-> All checks passed

uv run ruff format --check src tests scripts
-> 154 files already formatted

uv run python -c "import vqapr; from vqapr.runtime.timeline import Timeline; ..."
-> vqapr Timeline

uv build
-> built dist/vqapr-0.1.0.tar.gz and dist/vqapr-0.1.0-py3-none-any.whl

git diff --check
-> passed; Git emitted only the checkout's LF-to-CRLF warnings
```

## Remaining limitations and follow-up

- This slice does not persist a derived calendar in `Workspace` or record its source dataset. The
  registered-dataset read path and persistence belong to rewrite step 2.
- The pure derivation function trusts that the data layer selected dates according to the frozen
  rule. That integration must validate the rule-specific query and source identity.
- A Timeline currently sorts already constructed Event values. Trigger cadence, warm-up skips,
  fill convention expansion, preflight comparison, and Flow dispatch are intentionally absent.
- Calendar future visibility remains the explicit open decision in architecture §15-1.
