# 133 — the surface, the scaffolds and the claim

**Closes:** `docs/issues/archive/036`. **Advances:** `docs/issues/archive/052` (the three showcases; the gate half
stays open). **Step:** M1.4, the last slice of M1 in
`docs/refactoring/2026-09-02-the-convergence-campaign.md`.
**Authority:** `docs/design/the-panel-the-surface-and-the-run.md` §3 · records `130`–`132`.

## Why this exists

Records `130`, `131` and `132` each made one role one class. What none of them did was read the
sentence `036` is named after — `SKILL.md`: *"Both are authored the same way"* — as an author
would, and check that every place an author looks now says the same thing. This record is that
reading, and the small number of places where it was still false.

## What was verified, and how

**Every name `vqapr.public` shares with `vqapr.authoring` is the same object.** Measured over
`authoring.__all__`: eleven names shared, eleven identical, zero different. Nine names live on
`authoring` only — the call contracts, `Observation`, `EconomicAccountView`, `AccountHistory`,
`AccountHistoryInput`, `Model`, `requirements_for` — and that is a choice rather than a gap: the
three scaffolds all import `authoring`, so the types an author is *handed* are read from where an
author writes, and `public` keeps the verbs plus the names an author subclasses or returns.

**The three scaffolds emit one grammar.** `from vqapr import authoring as va` in every kind and no
`vqapr.public`; `inputs()` as the one declaration; `.read(alias)` as the one read verb; and each
kind differing only in the verb that is its own (`decide` / `compute` / `project`+`monitor`). Three
tests in `tests/extension/test_one_authoring_surface.py` now assert this over `render()`, so it
cannot come apart quietly.

**`_internal/` holds no bridge.** `atomic.py` and `filelock.py`, and the boundary test's permitted
list names no extension-authority edge.

## What was still false

**`SKILL.md` described a DataModel's rows in the old shape.** *"What a DataModel is handed"* named
`context.window.observations(requirement)`, `ObservationBatch`, `.rows` as a tuple of dicts and
`window.snapshot(requirement)` — the read verb records `128`–`131` replaced. It now describes
what every role is handed: `inputs()` → alias → `va.DatasetInput`; `.read(alias)` → a tuple of
`Observation`s with `instrument_id`, `available_at` and `values`. The constraint paragraph said
*"five members"*; it says two members and two consumers, and that a breach is recorded rather
than fatal (`130`). The strategy sketch had no import line — `036` pointed at exactly that: *"it
endorses neither"* — and now shows the class, the import and `self.memory`.

**The identity suite's own docstring said the package was wrong.** It was written as a
characterization suite counting down to this record; the docstring now states what it specifies.

**Three showcases, the same three `052` measured.** They registered the shipped cap without the
`benchmark_dataset_id` it has required since the enhanced-index work, though each of them
registers exactly that dataset under the same id. One config key each. Past that, they read
`bounds.lower`/`bounds.upper`, the attribute names record `130` replaced with
`lower_weights`/`upper_weights`. Past that, `show_005`'s monitoring report read `measured`,
`bound` and `excess` off a finding in the run's report, and record `130` had put the author's
values one level down, under `StampedConstraintFinding.finding`, proxying only `passed` and
`offenders`. All three are the showcase rot `052` describes — a contract moved and nothing ran the
showcase. The first two are repaired in the showcase. The third is repaired in the package:
`StampedConstraintFinding` reads `measured`, `bound`, `excess` and `details` through, for the
reason it already read `passed` through — a reader of `report.findings` holds one object per
constraint, and the snapshot a breach leaves behind (which constraint, the bound, the value) is
what that object is for. Same values, one access path; the showcase is unchanged there.

## Trade-offs

**`052`'s gate half is still open.** Nothing in `pytest` runs `showcases/`, so the next contract
move will rot them again; this record measured them by hand, as `130`–`132` did. It stays on the
ledger as the issue it is.

**`036` closes with its table answered, not deleted.** The reporter's ten-row table is re-read at
the end of the issue file with what is true now; two rows should differ (the verb and the return),
and eight are identical.

## Validation

```
uv run ruff check src/                           All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs         1256 passed, 14 deselected
PYTHONUTF8=1 uv run pytest tests/ -q -m slow -rs  14 passed
```

Branch parent `develop @ abc5a36b` (record `132` merged), measured: **1253 passed / 14
deselected** fast; showcases **6 of 9**.

**Showcases: 9 of 9, up from 6.** `show_005`, `show_006` and `show_008` complete; every other
showcase was re-run in record `132` on the tree this branch starts from.
