# 061 -- `window.values[name]` builds every column of the window, and the docstring says the window is not a copy

**Status:** **CLOSED 2026-09-03** by record `143` (deletion campaign Step 2b). `values` is a lazy mapping that converts one column per name asked for; `latest()` and `counts()` stay in Arrow; the docstring states the cost. No `tail(n)` -- the accessor removes the measured cost.

**Status when filed:** open. Found 2026-09-03 by the scenario testbed run 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-013**), against `vqapr-0.3.0`. Confirmed
against source the same day; the source is worse than the agent measured.

**Touches:** `src/vqapr/data/panel.py:198-201` (`PanelWindow.values`) and `:156-161` (the
docstring, *"a 2d slice, not a copy"*); `:203-212` (`latest`, same loop).

## What was measured

A strategy that retrains every 125 sessions on 1,000 days and otherwise wants the last 30
residuals per name declares `RowsLookback(rows=1030)`. Per callback, 2,145 names, probe strategy
`work/decl/probe_lookback.py`:

| | |
|---|---|
| `call.read("resid", "resid")` | 0.09 s |
| iterating every column of `values` | 0.31 s |
| slicing the last 30 of every column | 0.31 s |
| first callback (panel build) | 30 s |

So `values[name][-30:]` on the 124 sessions that only want 30 costs exactly what reading the whole
1,030-row column costs -- 2.2 M cells for 64 K wanted -- and over a 2 x 2 grid of strategies that
is an hour. Nothing documents the cost; the probe was the only way to learn it. The agent
restructured the strategy to read the full history only on retraining days and use `latest()`
otherwise, which still pays the same 0.3 s.

## Why

`values` is a property that returns `MappingProxyType({name: self.series(name) for name in
keys})` -- **every** name's tuple is built on each access, before `[name]` selects one. So
`values[name]` is not "one column"; it is the whole panel, then one column of it. `latest()`
walks the same loop. The window itself is a slice, as the docstring says; the accessor is a copy
of everything.

## What to do

- Make `values` a lazy mapping whose `__getitem__` calls `series(name)` for that name only.
- Add `tail(n)` (or `series(name, last=n)`) so a long declared lookback can serve a short daily
  read without a second `DatasetInput`.
- Say in the `PanelWindow` docstring what an access costs, and that two `DatasetInput`s with two
  lookbacks is the way to have a cheap daily read and an expensive periodic one if `tail` is not
  added.
