# 038 — One `instruments:` list filters every requirement, so a second dataset's row keys must be enumerated as instruments even when they are not instruments

**Status: CLOSED 2026-09-01** by [`123-a-field-is-an-expression-and-instrument-is-optional.md`](../implementations/123-a-field-is-an-expression-and-instrument-is-optional.md)
(lane C of the read-path campaign). `instrument_field` is optional at registration, and a dataset
registered without one has no instrument axis: no instrument predicate, no instrument column, and
the declared instrument list is not applied to it.

**The "better fix" was adopted one layer lower than this file proposes**, on the dataset rather than
on the requirement — whether a table is keyed by instrument is a fact about the table. The
completion condition is `test_criterion_2_a_dataset_with_no_instrument_axis_is_not_narrowed`, which
registers this file's own `kimchi-ff5` shape and reads it with no factor id in `instruments:`.

The cheap docs fix this file also named is superseded, as it said it would be: the sentence would
document a behaviour that no longer exists.

Originally scheduled under the campaign anchored at
[049](049-following-the-packages-own-data-guidance-costs-six-hundred-times.md).

This file asks for a **per-requirement** instrument scope. The ruling puts it on the **dataset**:
`instrument_field` becomes optional at registration, and a dataset registered without one has no
instrument axis, so the declared instrument list is never applied to it.

**Why lower is righter.** Whether a table is keyed by instrument is a fact about the table. `RMRF`,
`SMB` and `HML` are not instruments for *any* reader, so letting each requirement re-assert that
invites two readers of `kimchi-ff5` to disagree about it — and one of them to be wrong silently. It
also means the author declares it once, at the only moment they are looking at the data's columns.

The owner's framing, recorded because it is the reason this is not treated as a new feature:
**a dataset with no instrument axis should have been registrable all along.** `DatasetRegistration.of`
takes `instrument_field` as a required keyword argument, so a factor-return table is registrable
today only by inventing an instrument column for rows that are not instruments. That is a gap, not
an extension, and it is why this is scheduled rather than designed.

Job (2) separates from jobs (1) and (3) exactly as this file argues. The cheap docs fix it also
names is superseded — the sentence would document a behaviour that is being removed.

**Status when filed:** open. Found 2026-08-30 by the first-time-user journey in
`kaist-thesis/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-015**,
`slowed` / `docs`.
**Touches:** `ModelWindow` requirement filtering; `MaterializationSpec.instruments`; the run spec's
`instruments:`; `SKILL.md`'s DataModel paragraph.

## The model

The Fama-French residual arm reads two datasets: `krx-daily` for stock excess returns, and
`kimchi-ff5` for the five factor series. The DataModel contract supports this cleanly —
`requirements()` returns a tuple, so the author returns two `DataRequirement`s and calls
`observations()` on each.

## What the author expected

That `instruments:` in the materialization spec names *what the model is evaluated over and emits
rows for* — the 873 stocks. The factor requirement reads a different dataset whose row keys are
`RMRF`, `SMB`, `HML`, `RMW`, `CMA`. Those are not instruments, not tradable, not in any exchange
listing, and not things the model emits output for.

## What arrived

Zero factor rows:

```
{"status": "short_factor_window", "n_stock_rows": 62572, "n_factor_rows": 0, ...}
```

then a refusal:

```
"observed": "all 1 invocation(s) returned zero rows",
"requirement": "materialization must produce at least one output row",
"fix": "...at least that many rows before the earliest evaluation instant. Otherwise widen the
        requested instruments/evaluation_times, or fix DataModel.compute to emit rows"
```

Adding the five factor ids to `instruments:` — changing nothing else — produced `n_factor_rows: 365`
(73 sessions x 5 factors) and 713 residuals.

So `ModelWindow` filters **every** requirement by the single declared instrument list, across
datasets. A dataset keyed on factor names, macro series, index levels or anything else non-tradable
must have those keys enumerated in `instruments:` alongside the real ones.

## Why it is awkward rather than merely surprising

**One list is doing three jobs:**

1. the universe the model is evaluated over,
2. the row filter applied to every dataset it reads,
3. the closed set of things it may emit — enforced by
   `materialize.output.instrument_unrequested` (see issue 032).

Those three coincide for a single-dataset model and diverge the moment a model reads a second
dataset keyed on something else. Returns plus factors is the most ordinary two-dataset model there
is, so this is the first thing a factor replication hits.

**It also leaks into the run spec.** A simulation's `instruments:` feeds the exchange listing check,
and every instrument there needs a listing or preflight refuses it by name. So the *same* list that
must contain `RMRF` for a materialization must **not** contain it for a run, and the two have to be
maintained separately for what is conceptually one universe.

## The refusal, fairly

It does say *"widen the requested instruments"* — one of three alternatives, alongside lookback
coverage and a broken `compute`. It was not wrong. But it did not say which of the three applied,
and what actually identified the cause was the author's own profiling line (`n_factor_rows: 0` next
to `n_stock_rows: 62572`). Without that instrumentation they would have gone after the lookback
first, since the fix text leads with row coverage.

**Cost:** ~10 minutes, including writing the two-variant experiment to be sure.

## What would close it

The cheap fix is one sentence in the skill's DataModel paragraph: *"a window is filtered by the
declared instruments for every requirement, so a second dataset's keys must be listed too."*

The better fix is a per-requirement instrument scope, so a factor requirement can declare that it is
not instrument-scoped — which would also separate job (2) from jobs (1) and (3), and remove the need
to maintain two divergent copies of one universe.
