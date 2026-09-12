# 143 — a window column is converted when it is asked for

**Closes:** `docs/issues/archive/061`. **Step:** 2b of `docs/refactoring/2026-09-03-the-deletion-campaign.md`
-- a bounded step taken between Step 2 and Step 3 because the finding arrived from the `0.3.0`
scenario testbed while Step 2 was on the same read path, and the fix is small.
**Authority:** record `137` (the panel is a slice, not a copy) and the `035` ruling.

## Why this exists

`PanelWindow.values` was a property returning `MappingProxyType({name: self.series(name) for
name in keys})`: every name's column was converted to a Python tuple on each access, before
`[name]` picked one. A strategy on 2,145 names with `RowsLookback(1030)` paid 2.2M cell
conversions per callback for the 64K it wanted, and `latest()` walked the same loop; the docstring
said the window was not a copy. `counts()` -- called on **every** read to fill the access record's
`actual_rows` -- converted every column too, so a read that touched one name still converted
the whole window.

## What changed

- **`PanelWindow.values`** is `_LazyColumns`, a read-only `collections.abc.Mapping` whose
  `__getitem__` is `series(name)`. `values[name]` converts that column once per window and
  caches it; `len`, `in`, iteration and `== {...}` mean what they did.
- **`latest()`** stays in Arrow: `pc.drop_null` on the name's slice and one scalar `as_py()`.
- **`counts()`** is `len(column) - column.null_count` per name: no conversion at all.
- **`_column(name)`** is the one place the slice and the unknown-name refusal live; `series`
  uses it.
- **Docstring** states what an access costs and how to have a cheap daily read beside an
  expensive periodic one (two `DatasetInput`s with two lookbacks). No `tail(n)`: the lazy
  accessor removes the measured cost, and a second verb for the same window is not asked for
  by a consumer yet.
- **Test.** `tests/data/test_panel.py`: after `values["A"]`, only `A` is in the conversion cache;
  `latest()` and `counts()` leave it empty.

## Validation

```
uv run ruff check src/                              All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs            1322 passed, 21 deselected  (branch point: 1321 / 21)
PYTHONUTF8=1 uv run pytest tests/showcases -m ""    9 passed
```
