# 151 — a window has a cross-section: `PanelWindow.current()`

**Closes:** `docs/issues/archive/072`. **Branch:** `step-01-072-current`, off `develop @ ed3c348c`.
**Campaign:** `docs/refactoring/2026-09-04-the-one-shape-campaign.md`, Step 1. **Authority:** the
owner, 2026-09-04.

## Why this exists

A `PanelWindow` had four accessors -- `values`, `latest()`, `counts()`, `max_available_at` --
and none answered "this name's value at the evaluation instant, or nothing". `latest()` is the
closest in name and returns the newest non-null value per name *anywhere in the window*. On a
sparse panel (a residual-legs table with a row for a name only on sessions it was eligible) the
scenario testbed's run 3 read it as the cross-section and traded ineligible names on loadings up
to a week stale, about 1% of name-days, concentrated on the first session of each month. Nothing
in the package could see it: every value involved was legitimately available at the decision
instant, so no point-in-time check fires. The surface invited the mistake.

## What changed

- `PanelWindow.current()` (`src/vqapr/data/panel.py`): the value at the window's last instant
  per name; a name whose cell there is null or absent is not in the mapping. One Arrow scalar per
  name, no column conversion (the same cost class as `latest()`); an empty window returns an
  empty mapping; a panel with no instrument axis returns one entry or none.
- `latest()`'s docstring now says what it is -- a time-series read, however old -- and points
  at `current()`; the `PanelWindow` class docstring lists both.
- The three `read()` docstrings in `vqapr.authoring` (`DataCall`, `StrategyCall`,
  `ConstraintCall`), the skill's `read(alias, field)` paragraph, and the strategy/constraint
  scaffolds name `current()` as the cross-section and `latest()` as the carried-forward value.

## Decisions

- **A new verb, not a changed one.** `latest()` keeps its meaning: a name's last value is a real
  question (a monthly stamp read daily), and changing it would silently move every existing
  caller. The issue's alternative -- `latest()` carrying its instant -- makes the author compare
  timestamps by hand for the common case.
- **No access-record field.** The issue asked whether the record should say a read returned a
  stale value for some names. Not taken: the record describes what was read, not how the model
  interpreted it, and `current()` makes the mistake unwritable rather than reportable.

## Validation

- `tests/data/test_panel.py::test_current_is_the_cross_section_and_latest_carries_forward`: on
  the fixture whose `volume` is null on the 6th, a window ending on the 6th has
  `latest() == {A: 10.0, B: 20.0}` and `current() == {}`; on a dense field the two agree; an
  empty window gives two empty mappings; `current()` converts no column.
- The no-instrument-axis test asserts `current()` equals `latest()` on a one-column panel.
- `ruff check src/` clean; `tests/data/test_panel.py` 11 passed; `tests/extension` and the KRX
  cost journey (the one CLI test that calls `latest()`) green. Full fast suite: see the merge
  commit.
