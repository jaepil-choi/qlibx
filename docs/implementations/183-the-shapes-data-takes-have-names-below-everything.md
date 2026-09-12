# 183 — The shapes data takes have names, below everything

**Date:** 2026-09-08. **Branch:** `redesign/component-eventloop` (campaign M3; plan
`.agent/plans/active/component-eventloop-redesign.md`). **Review:**
`docs/code-review/2026-09-08-four-readers-one-loop-and-the-missing-shapes.md` §3, §8-3.

## Why

The owner: *"우리 프레임워크에서 데이터의 형태가 있는데 보통 data가 feed 되면 2d wide panel 형태거나
long dataset이란 말이야 ... 이런 model/domain이 충분히 정의되지 않은 것 같아."* The review
counted five shapes and one and a half types: `Panel`/`PanelWindow` (wide, Arrow) in `data/`,
`Observation` (long) on the author surface, and the cross-section -- one instant's instrument
-> value, the shape every judgment is spoken in -- as `Mapping[str, Decimal]` in fifty-eight
places, with its operations (elementwise max/min to merge bounds, abs, argmax, a total)
re-written by each consumer. `Grain`, the fact the shapes are derived from (owner ruling B,
2026-09-02: the grain decides the verb), lived in the registration module.

Whether the cross-section should be Arrow-backed was decided by measurement, not design
(`scratchpad/bench_xs.py`, 3,000 names): the arithmetic is ~10 ms per callback in dict+Decimal,
a real run spends its 356 s on data movement (issue `068`), and `optimize` is exact-rational.
So the type is thin and its cells stay `Decimal`.

## What

`src/vqapr/domain/shapes.py`:

- `Grain` -- moved from `data/datasets.py`. Its docstring now says what it is not: a point
  read is a way of reading decided by the event, not a grain (owner ruling: no `Grain.POINT`).
- `Scalar`, `Row`, `Rows`, `normalize_scalar`, `normalize_rows` -- moved from the
  banner-folded `rows.py` section of `domain/values.py`; a row is the long shape's unit.
- `Observation` -- moved from `authoring.py`, which re-exports it; `_framework_row` unchanged.
- `CrossSection[T]` -- a `Mapping[str, T]` with sorted, validated instrument keys, an optional
  `at`, and `map`, `elementwise`, `where`, `total`. `Mapping` semantics are kept
  (`eq=False` on the dataclass), so `weights == {...}` and `dict(weights)` mean what they did.
  `_trusted` is the framework's door for cells it already proved.
- `Series[T]` -- one instrument's cells over a window's instants; `latest()`, `present()`.
- `Panel` -- a runtime-checkable protocol (`instants`, `instruments`, `current`, `latest`,
  `series`) that `data.panel.PanelWindow` satisfies.

Consumers:

- `PanelWindow.current()` and `latest()` return `CrossSection`; `current()` carries the
  window's last instant as `at`, `latest()` none (each name's newest value may sit on a
  different row). `series(name)` returns a `Series`; `values[name]` keeps returning the cell
  tuple through the new `_cells` (issue `061`'s once-per-window conversion is unchanged).
- `authoring._copy_weights` returns a `CrossSection[Decimal]`, so `Rebalance.target_weights`,
  `ConstraintBounds.lower_weights`/`upper_weights`, `EconomicAccountView.positions`/`values`
  hold one; their annotations stay `Mapping[str, Decimal]` because that is what an author
  passes in (a dict). `EconomicAccountView.weights()` returns a `CrossSection` at the NAV's
  observation instant.
- `constraints.evaluation.merged_constraint_bounds` is `elementwise(max)` / `elementwise(min)`;
  a projection covering different names is refused by the shape.
- `vqapr.public` exports `CrossSection` and `Series`; `Grain` is imported from its new home.

## Trade-offs

- **Annotations say `Mapping`, values are `CrossSection`.** The dataclass boundary accepts
  what an author types and stores the shape; a field annotated with the stored type would
  make every author's dict a type error. M5's pydantic models close this properly: a
  before-validator turns the mapping into the shape and the field is annotated with the shape.
- **`AccountHistory.series` / `.panel` are not converted.** They are account-level and
  per-instrument tuples with their own declaration; converting them is a `Series` per name and
  was not asked for. Noted for M4/M5.
- **The execution snapshot's prices stay a dict** in `ExecutionHandler`; M4 replaces the
  snapshot with an `ExecutionCall`, which is where the cross-section belongs.

## Validation

- `uv run pytest tests/ -q` (fast set): passing; `tests/domain/test_shapes.py` added.
- `uv run ruff check src/`: clean. `uv run pyright`: 181 errors, unchanged.
