# 031 — The one type every DataModel author must consume is not importable from `vqapr.public`

**Status:** **CLOSED 2026-08-31** by
`docs/implementations/100-the-window-states-its-own-shape.md` (branch
`fix/031-observation-batch-is-public`). `ObservationBatch` is exported from `vqapr.public` with a
docstring naming its row keys, its ordering guarantee and its value types; `ModelWindow` joined
`__all__` with it, since the shipped constraint scaffold already imported it from there;
`observations` gained a docstring; and the skill's DataModel section states the shape.

**One answer in this file is corrected.** "values arrive as `float`, not `Decimal`" is true of the
reporter's source, not of the type: a DOUBLE column returns `float` and a DECIMAL column returns
`Decimal`, in the same row. The docstring states that rule, and
`tests/data/test_observation_batch_shape.py` proves both — along with the ordering, which was the
open risk this file named.

**Status when filed:** open. Found 2026-08-30 by the first-time-user journey in
`kaist-thesis/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-005**,
`urge` / `docs` — the run's first recorded urge to open the source.
**Touches:** `src/vqapr/data/windows.py` (`ObservationBatch`); `src/vqapr/public.py`;
`src/vqapr/agent/skill/SKILL.md`.

## The gap

`ModelWindow.observations(requirement)` is the only method a DataModel author can call to see any
data at all. Its signature names its return type:

```
inspect.signature(ModelWindow.observations)
  -> (self, requirement: DataRequirement) -> 'ObservationBatch'
```

Everything the author does next depends on that type's shape. What the public surface offers:

| probe | result |
|---|---|
| `hasattr(vqapr.public, "ObservationBatch")` | **`False`** |
| `from vqapr.data import ObservationBatch` | `ImportError` |
| `ObservationBatch` in `SKILL.md` | absent — so is `.rows` |
| docstring on `ModelWindow.observations` | none |
| the scaffold from `vqapr new datamodel` | uses `.rows`, `row["excess_return"]`, `row["instrument"]` — never a timestamp, never a pivot |

Verified still true on `develop`: `ObservationBatch` is defined in `src/vqapr/data/windows.py` and
is not among `public.py`'s exports.

## The three questions the author cannot answer, and why they are load-bearing

1. Does a row carry its own `available_at`, or only the declared `fields=(...)`?
2. Are rows ordered by time? The scaffold computes `values[-1] / values[0] - 1` and calls it a
   trailing return — true only if they are, and said by arithmetic rather than by statement.
3. Across many instruments, is `rows` one flat interleaved sequence, or grouped by name?

None of this is pedantry for a cross-sectional model, which is the shape of most of the factor
literature. The reporter's target — PCA residuals over ~800 names — needs a (date × instrument)
matrix, and cannot build one from a flat sequence without knowing (1) and (2). The single worked
example the package ships is a per-instrument reduction (`history[instrument].append(value)`), which
answers a different question.

`ModelWindow` itself has a good one-line docstring, and `.snapshot` has a genuinely useful one
(*"The newest cross-section only: rows at the latest `available_at` per instrument"*) — which is
the closest thing to evidence that rows are organised by `available_at`, and it documents the method
the author is **not** calling.

## What it cost, and what the reporter did instead

They did not open `.venv/.../vqapr/data/windows.py`, and recorded the urge instead. The answer was
obtained by registering and materializing a throwaway DataModel whose `compute` reports
`sorted(rows[0].keys())`, the row count and whether the sequence is non-decreasing in time — a full
register → materialize → show cycle to learn one type's field names.

The answers, for the record: a row **does** carry `available_at`; rows **are** ordered by
`available_at` with instruments interleaved within each instant; values arrive as `float`, not
`Decimal`.

**The residual risk is the reporter's own closing note.** That ordering was confirmed on one window
of three names at one instant, and every residual in the run then depended on it. Nothing in the
package promises it.

## Relationship to 021

Adjacent, not the same. 021 is about helper families in `vqapr.public` that exist and go unmentioned
by the skill. This is a type that **is** mentioned — in a signature the author will read — and
cannot be imported.

## What would close it

Export `ObservationBatch` from `vqapr.public` with a docstring naming its row keys and stating its
ordering guarantee. Failing that, two sentences in the skill's DataModel paragraph, or a second
scaffold flavour that reads a cross-section rather than a per-name reduction.
