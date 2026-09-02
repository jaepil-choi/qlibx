# 113 — Three findings from the Step 7 review

**Closes:** R1, R2 and R8 of `docs/diagnostics/2026-08-31-post-step-07-review.md`, an independent
review of Steps 7–8 written by a second agent.
**Branch:** `step-08b-the-review-findings`.

Two of the three are defects **in my own work**, and one is a severe pre-existing defect that Step 7
relocated verbatim. All three are cheapest to fix now, while the code has just moved.

## R1 — a completed run was discarded because a roster file went bad after it finished (severe)

`flow/orchestration.py`:

```python
try:
    result = flow.run()
    if writer is not None:
        freeze_record(writer, result, frozen, as_loaded, roster_report(root_path, registry))
except BaseException:
    if writer is not None:
        writer.release()
    raise
```

`roster_report(...)` was evaluated **as an argument, inside the `try`**. It re-reads the roster
pointer, so a pointer corrupted during the run — a crash mid-write, a concurrent `vqapr register`, a
hand edit — makes it raise `workspace.instruments.unreadable`. That is not speculation:
`tests/flow/test_a_damaged_roster_pointer_is_not_no_roster.py` already asserted it does.

The consequence: `flow.run()` **returns successfully**, then `roster_report` throws, `freeze_record`
is never entered, the writer releases, and the exception propagates. No rows, no `record.json`, so
`run_ids` does not count the run as finished, the run id is freed for a peer to take, and the CLI
exits 1. **A multi-hour computation disappears because one small JSON file went bad after it was no
longer needed.**

What makes it worse is that the repository already knew. `cli/run.py` carries the defence, written
out in full:

> **This runs after the run completed and its record is on disk.** […] Here it would be wrong: the
> tables can become unreadable in the minutes a real run takes, and letting that refusal escape
> would report exit 1 for a run that completed.

That guard runs *after* `run()` returns, so it never covered the line inside it. The person who
wrote the defence and the place that needed it never saw each other.

**Fixed** by evaluating the report outside the argument list, which catches `VqaprError` **only** —
a bug in report construction still fails loudly. The report is decoration on a record; the record is
the run.

> **CORRECTION, record `115`.** This paragraph originally ended "Two tests: one that a damaged
> pointer no longer costs the record, one that a `TypeError` still escapes", and the table below
> claimed `7 passed (was 5; +2 for R1)`. **Both were false.** The heredoc meant to append those
> tests failed with `Bad file descriptor`; the file's pre-existing parametrised count of 7 was
> mistaken for evidence they had landed; and this fix — the most severe finding of the review —
> shipped entirely unexercised. Found by an independent architecture review of VB002. The tests now
> exist in `tests/flow/test_a_completed_run_survives_a_broken_roster.py`.
>
> Record `115` also corrects the fix itself: absorbing the failure as `None` wrote a falsehood,
> because `roster: null` is defined by this record's own contract as "the run never knew the
> categories" and any run reaching that line had read its roster. It is a stale marker now.

## R2 — `evidence/` imported `flow/`, which is backwards

My Step 7 put `freeze_record` and `contract_report` in `evidence/records.py`, following the plan.
The plan was wrong on this point and I did not check it: the module imports `FrozenRun`,
`RECORD_FIELDS`, `RunRecordWriter` and `SimulationResult` — **three `flow` modules** — while
`evidence/` is spine and `flow/` is the dispatch loop above it.

A run record is a flow artifact. `RECORD_FIELDS` and `RunRecordWriter`, the two things this builds
against, live in `flow/run_records.py`. **Moved to `flow/records.py`**, beside them, and the
inversion is gone rather than documented.

## R8 — I set the gate above the value it was gating

Step 7's acceptance: *"`public.py` 775 → **under 250 lines** with `__all__` UNCHANGED."*

`__all__` is byte-identical, 132 names, verified by AST. That half was kept. The line count was not:
the file came out at 351, and the ceiling I wrote to police it was **420** — 69 lines above the
actual value and 170 above the target. The next step could have added 69 lines to the documented
surface and stayed green.

That is the exact failure record `105` opened this campaign by fixing: *a configured gate that is
open is not a gate.* I wrote one anyway, in the test whose purpose was to prevent it.

**Fixed two ways, because one alone would still hide something.**

`MAX_LINES` is now the exact current value (**328**), a ratchet rather than a budget, with the
history in its docstring so the next reader sees what it was and why.

And the 250 target is amended rather than quietly missed. Measured: of the 328 lines, **115 are
imports and 139 are `__all__`** — 254 lines of pure surface declaration for the 132 names this
module exists to export. The rest is the docstring, blank lines, and eight thin `register_*`
delegations. **250 was not reachable without dropping public names**, which is a different decision
from moving orchestration out, and one nobody took. The number was wrong; the work was not. Saying
so is better than a loose constant that lets both look fine.

## Validation

| check | result |
|---|---|
| `evidence/` → `flow/` imports | **3 → 0** |
| `MAX_LINES` | 420 → **328**, equal to the real value |
| `tests/flow/test_a_damaged_roster_pointer_is_not_no_roster.py` | 7 passed — **but unchanged by this record; see the correction above. R1 had no tests until record `115`.** |
| `tests/boundaries/` | 37 passed |
| fast suite | **1475 passed**, 14 deselected |
| **`-m slow -rs`** | **14 of 14 passed**, no skip lines |
| `uv run ruff check src/` | All checks passed |

The remaining findings — R3 through R7, R9, R10 — are recorded in the review and not addressed here.
R5, R6 and R7 concern the authoring contract and the facade tripwire's exemption list, which are
Steps 9 and 13; R3 and R4 are the roster's read path, which R1 touches but does not resolve.
