# 096 — A panel read is a Python loop over instruments: the sample strategy loops because the API offers nothing else

**Status: CLOSED 2026-09-10 -- records `232` (a field is one block; `PanelWindow.matrix()`;
vectorised `counts`/`current`/`latest`; the panel built from the scan's columns) and `233` (the
sample strategy and both scaffolds compute on the matrix).** exp_231 at 3,000 names: `counts()`
3.1 -> 0.2 ms, the sample decision 12.3 -> 1.5 ms. Filed the same day from the 0.11.0 spine
trace; plan `.agent/plans/active/one-door-campaign.md`, milestone P.

| | |
|---|---|
| vqapr version | `0.11.0` (develop `05dbc1f5`) |
| reported | 2026-09-10 |
| reporter | owner, reading `SampleReversal5d.decide` |
| evidence | trace `06_run_short` (`#17482`-`#17581`), `exp_231` bench |

## What the owner asked

> 왜 decide 하는 안에서 instruments를 가지고 for loop을 도는거지? 5일 close lookback 받은 2d
> panel을 가지고 axis=0 으로 mean 해주고 부호만 - 로 해주면 되잖아.

## What the code does

`Panel` (`data/panel.py:66`) holds `columns[field][instrument]`: **one Arrow array per
instrument**, not one block per field. There is no two-dimensional accessor. Every accessor on
`PanelWindow` walks the instruments in Python:

| accessor | per read |
|---|---|
| `values[name]` (`_LazyColumns.__getitem__`) | one slice + `to_pylist` per name asked |
| `counts()` | `_column` per name -- called by the framework itself on **every** read (`data/store.py:270`, the access record) |
| `current()` | `_column(name)[last]` per name |
| `latest()` | `pc.drop_null` per name |

The trace shows it at ten names: one callback's read is `PanelWindow.values` -> `_LazyColumns` ->
`_cells` -> `_column` ten times over (`#17532`..`#17581`), and `counts()` ten `_column` calls
before that. The sample strategy (`agent/sample/reversal_5d.py`) and the scaffold the CLI emits
(`extension/scaffold.py:41`, `:119`) loop over `window.instruments`, convert each cell to
`Decimal(str(v))`, and reduce per name -- because that is the only shape the API hands them.

## Measured (exp_231, 3,000 names x 6 instants, best of 3)

| | ms |
|---|---|
| sample `decide` as written (per-name loop, Decimal per cell) | 8.8 |
| `PanelWindow.counts()` (the framework's own, every read) | 3.1 |
| `PanelWindow.current()` | 3.6 |
| the same decision on a `(instants x instruments)` float64 block, numpy | 0.1 |
| building that block from the panel, once per panel | 10.7 |

Same answer (the bench asserts it). Per callback that is ~12 ms of Python loops at 3,000 names;
on a minute-grained agenda (390 callbacks a day) it is 4.7 s a day, and it grows with the number
of fields read. The panel build itself is worse: `observation_rows` returns one dict per row and
`Panel.from_rows` pivots them in Python -- 425 ms for 10 x 735 rows in the trace (`06 #9480`,
`#16422`), which does not stay small at 3,000 x 735.

## Proposed fix (milestone P of the plan)

- `Panel` holds, per field, one `(instants x instruments)` block: a float64 `numpy` array with
  `NaN` for a missing cell when the field is numeric or boolean, an Arrow array otherwise. Built
  from the scan's **columns** (`observation_columns`, an Arrow table), pivoted with one fancy-index
  assignment, not from dict rows.
- `PanelWindow.matrix()` returns the window's rows of that block as a view (`block[start:stop]`),
  and `instruments`/`instants` say what the axes are. `counts()`, `current()`, `latest()` become
  vectorised over the block. `values[name]` and `series` stay, built from a column of the block.
- The sample strategy, the scaffold, the datamodel sample and the `make-strategy` /
  `make-datamodel` skill references are rewritten on `matrix()`: the reversal is
  `closes[-1] / closes[0] - 1` over the block, `Decimal` appears once, at the `Rebalance`
  boundary. The showcase digest gate says whether float arithmetic reorders any tie.
- `tests/flow/test_hot_path_costs.py` gains a guard: one read of a 3,000-name window makes O(1)
  Python-level column calls, not O(names).
