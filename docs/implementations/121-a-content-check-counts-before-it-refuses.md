# 121 — A content check counts before it refuses

**Closes:** `docs/issues/archive/032-a-content-check-fails-fast-and-then-reports-a-count-of-zero.md`
(F-006, found by the first-time-user journey in `kaist-thesis/vqapr-final-testbed/` against
`vqapr-0.2.0a1`).
**Branch:** `fix-032-refusal-counts`.

`SKILL.md` promises that a check on row **contents** quotes up to five offending values and that
`example_total` says how many there were before truncation. Two checks on `DataModel` output —
`materialize.output.instrument_unrequested` and `materialize.output.instrument_duplicate` —
raised inside the per-row loop on the first offender, so they shipped `examples: []` and
`example_total: 0` while twenty rows were wrong.

## The decision, and why

The issue leaves the choice open: **scan and collect**, or **write an exception into the
`examples` / `example_total` contract naming the checks that cannot honour it.** This record takes
the first.

The deciding fact is where the issue came from: a first-time user's journey. Fail-fast on a
content check does not merely under-report — it hands the author a one-at-a-time loop. Twenty
stray instrument names means fix one, re-run the whole materialization, meet the next one, twenty
times over, with a `example_total: 0` at every step telling them nothing about how far they are
from done. That loop is exactly what the reporter experienced, and it is the cost the contract's
`example_total` field exists to remove.

The counter-argument for documenting the exception is cost: collecting means walking the rest of a
batch that is already known to be wrong. It is a weak argument here. The rows are already
materialized in memory and about to be discarded; the extra work is one pass of set membership
over output that never leaves the process. Nothing is published either way — the refusal is raised
before staging, and the workspace is untouched.

There is a second reason not to take the documentation route. `example_total: 0` does not read as
*"this check does not count"*; it reads as *"zero rows were wrong"*, which is false. Writing an
exception into `SKILL.md` would make the false number correct-by-declaration without making it
less misleading to anyone who did not read the exception. The number was the defect, not the
sentence describing it.

**Both checks are fixed, not one.** They have the same shape two branches apart; fixing only the
one the issue names would leave the next reader to rediscover the other.

## How it works

`_validated_output` in `src/vqapr/flow/materialize.py` now runs its per-row loop to the end for the
two content checks, accumulating offenders, and raises once the batch has been read:

| | before | after |
|---|---|---|
| `observed` | the first offending instrument, e.g. `"D00"` | `"20 unrequested instrument(s) across 21 of 23 output row(s)"` |
| `examples` | `()` | first five distinct offenders, in emission order |
| `example_total` | `0` | count of **distinct** offending instruments |

`example_total` counts distinct offending instruments rather than offending rows, and `examples`
quotes each offender once. This follows the idiom already established by
`dataset.register.key.duplicate` in `data/datasets.py`, which reports `duplicate_groups` — the
number of key *groups*, not the number of rows in them. It is also the count that answers the
question the field exists for: *one typo, or a systematic fault?* Five identical quotes would burn
the whole `MAX_EXAMPLES` budget saying one thing. The row count is not lost — `observed` carries
both the distinct count and how many of how many rows carried them.

`_error` grew two optional keyword parameters, `examples` and `example_total`, forwarded to the
single `Failure.bounded` construction that was already there. `Failure.bounded` does the
truncation, so no call site can forget the cap.

### What is unchanged, deliberately

- **The judgement criteria.** What counts as a violation is identical. In particular an
  unrequested instrument is still not also a duplicate: the old code raised before the duplicate
  branch could see the row, and the new code `continue`s without entering it into `seen`. This
  lane changed how violations are *reported*.
- **The structural checks stay fail-fast** — `available_at_owned`, `fields_invalid`,
  `instrument_invalid`. A row whose field set is wrong, or whose instrument will not parse, has no
  content to quote, so `examples: []` beside `example_total: 0` is the honest answer there. The
  issue says so explicitly.

### The one behavioural consequence worth naming

When a batch contains **both** a content violation and a structural one, which refusal you get can
now differ. Previously the first offending row in order won outright. Now a content violation at
row 5 no longer preempts a structural violation at row 30, because the loop keeps going and the
structural check raises when it is reached. The reverse — a structural violation at row 5 winning
over content violations later — is unchanged.

This is the right precedence: a malformed row is a fact about whether the output can be read at
all, and there is no useful content report to give while one is outstanding. No test pinned the
old ordering, and nothing in `SKILL.md` promises it.

## What changed

| file | change |
|---|---|
| `src/vqapr/flow/materialize.py` | `_error` accepts `examples` / `example_total`; `_validated_output` collects unrequested and duplicated instruments across the batch and raises once, with the count and up to five quotes |
| `src/vqapr/agent/skill/SKILL.md` | one paragraph in *Recovering from: component-contract* stating that the output-row checks scan the batch and the row-shape checks stop at the first bad row. The `examples` / `example_total` contract itself is untouched — the code now keeps it |
| `tests/flow/test_materialize.py` | two `DataModel` fixtures with **twenty** violations each, and three tests |

## Validation

`tests/flow/test_materialize.py`:

- `test_unrequested_instruments_are_collected_and_counted_not_reported_as_zero` — twenty distinct
  unrequested instruments on twenty-one of twenty-three rows. Pins `example_total == 20`,
  `len(examples) == MAX_EXAMPLES`, the five quoted names, and the exact `observed` string.
- `test_duplicated_instruments_are_collected_and_counted_not_reported_as_zero` — twenty requested
  instruments, each emitted twice. The sibling check, same assertions.
- `test_a_structural_output_check_still_stops_at_the_first_bad_row` — `available_at_owned` keeps
  `examples == ()`, `example_total == 0`, and stops at row 0. This also pins the `SKILL.md`
  invariant that an empty `examples` never sits beside a non-zero `example_total`.

**The fixtures carry twenty violations rather than one on purpose.** With a single offender,
fail-fast and collect-then-report produce the same `example_total`, so a one-offender test cannot
tell the fixed behaviour from the broken one. Verified by reverting only
`src/vqapr/flow/materialize.py` and re-running: both new tests fail (`assert 0 == 20`), the
structural test passes, which is the correct signature.

Gates, in the worktree:

```
uv run --no-sync ruff check src/                  ->  All checks passed!
PYTHONUTF8=1 uv run --no-sync pytest tests/ -q    ->  1513 passed, 5 skipped, 14 deselected
```

`ruff check tests/` reports nine pre-existing findings, none in a file this branch touched except
`tests/flow/test_materialize.py:195` (`F841 before`), which is present on the branch point and was
left alone.

**`tests/characterization/refusal_codes.baseline.json` did not move.** No refusal code was added,
removed, renamed or relocated to another file — only the payload of two existing codes changed —
and the standing gate is keyed on `(code, file)` with line drift reported but not fatal. The file
is byte-identical to the branch point, which matters because a concurrent lane edits it.
