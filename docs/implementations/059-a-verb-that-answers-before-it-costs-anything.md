# A verb that answers before it costs anything

## Why this exists

`preflight_run` raises on the first thing it finds. That is right for a gate standing in front of
a run — the first refusal is the reason the run must not start, and proving the rest costs time
nobody asked for.

It is wrong for the question an agent actually asks while preparing a declaration, which is *is
this ready*. Answered by a gate, that question costs one round trip per defect: fix the universe,
re-run, learn the period is reversed, re-run, learn the account holds a short the venue will not
fill. Each round trip is a full workspace open and re-read, and at no point does the reader learn
how many problems remain.

## What changed

`vqapr check <spec.yaml>` makes eight judgments, each answered independently, and reports all of
them at once.

```
check.universe.absent            a run with no instruments has nothing to decide about
check.period.uncovered           start and end must bound a real interval
check.execution.not_after_decision   a decision cannot fill at an instant already past
check.dataset.unregistered       every dataset a component reads must be registered
check.field.absent               that dataset must expose the fields the component names
check.lookback.uncovered         history must reach back past the run start
check.weights.mode_conflict      a long-only account must not open holding a short
check.weights.venue_conflict     a signed account needs listings the venue permits a short on
```

Independence is the design, not a property that emerged. Each judgment reads the spec and the
workspace and answers on its own, so a declaration carrying four defects produces four refusals in
a single call — asserted directly, and asserted from the other direction too: repairing one
judgment must leave the others reporting exactly what they reported before.

**It writes nothing.** Asserted byte-for-byte over `.vqapr/` by hashing every file before and
after, not claimed in a docstring. The claim stops precisely where it should: `check` imports user
code, because `weights` and `records` are Python and no component can be judged without loading
it. `loading.py` executes a user module through `spec_from_file_location`, so an imported module
can write anywhere it likes. The guarantee is about this package, and the verb's own docstring
says so rather than implying a sandbox.

**Blocked is a third answer.** A judgment that could not run because an earlier phase failed is
reported as `blocked`, naming what blocked it. Reporting it as passed would be a lie; omitting it
would make a partial report look complete.

## `new` refuses before it writes

AC-C6. `vqapr new strategy <id> --dataset <name>` used to scaffold against any name at all, emit
two files, and report success. The failure arrived one command later, from `register`, naming the
component's requirement rather than the flag that caused it — and the reader was left holding two
files to delete.

It now checks the workspace first and refuses, naming the closest registered id when the given one
is a near miss. Nothing is written. An unreadable or absent workspace is deliberately *not* a
refusal here: `new` is the command typed in an empty directory, and demanding a workspace before
the first scaffold would make the first command fail.

## Three no-ops caught before shipping

The venue judgment was written three times.

The first called `exchange.listing(id)`. Only `Academic` exposes that method; on a `KrxExchange` it
raised, the exception was swallowed, and the judgment found nothing — which reads exactly like a
pass. The second read `listings` as a sequence, which is Academic's shape; Krx keys a `Mapping` by
instrument id, so iterating it yielded bare strings and the judgment silently found nothing again.
The third reads both shapes.

None of the three would have failed a test that only asserted the code was *declared*. What caught
them was running the judgment against a real registered `KrxExchange` and demanding a refusal —
and that scenario is now the regression test, because a judgment that cannot fail is not a
judgment.

A related coupling was found the same way: an exception inside one judgment aborted the loop, so
an unrelated missing component suppressed every judgment after it. That quietly restored the
stop-at-first behaviour this verb exists to replace. Each judgment is now isolated, and one that
cannot answer records nothing rather than inventing a refusal or claiming a pass.

## Trade-off

`check` is not a second judge. A spec that cannot be read and a workspace that cannot be opened
already refuse with the framework's own codes, and those pass through untouched — re-coding them
as `check.*` would give one defect two names and break handling already written against the first.
What `check` adds to a passed-through refusal is the one thing the framework could not know: the
framework was handed ids, not a file, so it cannot say which spec named them. The two
`run.check.*` codes exist only for a bare framework invariant that has no code at all, which would
otherwise surface as `stage: unhandled` and tell an agent the framework broke when its spec was
wrong.

## Validation

```
uv run --no-sync pytest -q                                   # 1,150 passed
uv run --no-sync ruff check .                                # clean
python ../kwam-enhanced-index/vqapr-testbed-2/parity_probe.py --factors HML
```

Count gate MATCH: callback_days 2096, formations 97, membership_rows 110919. Value gate exact,
weight digests byte-identical to the Step 0 capture, so the step is parity-inert as predicted.

Four independent defects in one spec, one call:

```
check.universe.absent          list the instrument ids the run trades under `instruments:`
check.period.uncovered         set end later than 2025-06-01, or start earlier than 2024-01-01
check.weights.mode_conflict    drop A005930 from the initial account, or declare mode SIGNED
workspace.component.lookup.missing   register component 'absent', or use one of the ids listed
```
