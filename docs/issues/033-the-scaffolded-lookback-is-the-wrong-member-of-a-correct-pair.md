# 033 — `RowsLookback` is the scaffolded default, is undocumented, and is the wrong member of a correct pair for any cross-sectional model

**Status:** **CLOSED 2026-08-31** by
`docs/implementations/101-both-members-of-the-lookback-pair-are-reachable.md` (branch
`fix/033-the-lookback-pair-is-reachable`). All four of the places named below now say it: both
classes have docstrings, `vqapr new datamodel --calendar-lookback DAYS` emits the other member with
its own completeness guard, the skill names the pair and the span property, and each emitted
scaffold says which window it declared and what that window is for.

The calendar scaffold is held to the same gate as the rows one — it is registered, loaded and run in
`tests/extension/test_the_scaffold_offers_both_lookbacks.py`, not merely diffed.

**Status when filed:** open. Found 2026-08-30 by the first-time-user journey in
`kaist-thesis/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-007**
(`papercut` / `docs`) and **F-008** (`slowed` / `docs`); filed here as one issue because F-007 is
the first, wrong reading of the behaviour F-008 then measured.
**Touches:** `src/vqapr/data/lookback.py` (`RowsLookback` has **no docstring**);
`vqapr new datamodel --lookback`; `src/vqapr/agent/skill/SKILL.md` (names neither class).

## The behaviour is intended. The steering is absent.

Put to the user, who confirmed it directly: *"`RowsLookback` with `rows=` does fetch the last N rows
per instrument, that is correct. Otherwise you would have set the period with a lookback — that is
`CalendarLookback`."* The two classes are a deliberate pair, one indexed by rows and one by calendar
time. **This is not a bug report about the semantics.**

It is a report that an author following the only path the package lays down arrives at the wrong
member of that pair, and nothing on the way mentions the other one exists.

## How the reporter got it wrong, in two stages

**Stage one (F-007).** A probe with `RowsLookback(rows=5)` over three instruments returned 15 rows
spanning exactly five sessions. Conclusion recorded: *"`rows=N` is N sessions"*. The probe panel was
balanced, so *N rows per instrument* and *N sessions* were indistinguishable.

**Stage two (F-008).** First real materialization — 1,637 instruments, `RowsLookback(rows=313)`
(252 for the correlation matrix + 60 for the loadings + 1 to score), one evaluation instant:

```
[timing] load=4.13s total=4.66s rows=480202 T=1865 N=1562 kept=690
```

`rows=480202` is about 1,562 x 307, so the per-instrument count is honoured. But **T=1865**: the
batch spans 1,865 distinct sessions, back to roughly 2016, not the 313 sessions asked for. The panel
is unbalanced. A name that delisted in 2019, or one that trades thinly, still gets *its* last 313
rows. **The batch is the union of per-instrument tails, so its calendar span is set by the sparsest
name in the list, and is unbounded above.**

## Why this is dangerous rather than merely surprising

The obvious way to consume that batch is the scaffold's way — accumulate per instrument, take the
last N. Do that here and a 2024 correlation matrix quietly mixes a liquid name's 2023-24 returns
with a dead name's 2016-19 returns, because both are "the last 313 rows". The result is well-formed,
non-null, passes every check, and is wrong.

It is the failure mode the skill already warns about for `available_at` — *"a timestamp that is
wrong in meaning is still perfectly well-formed"* — one level up, at the window rather than the row.

The reporter did not ship it, by luck of habit: they pivot into an explicit (session x instrument)
matrix keyed on each row's own `available_at`, take the last 313 **dates**, and drop names with a
gap. Hence `kept=690` from `N=1562`. They had assumed the 872 dropped names were delistings rather
than time-misalignment.

## The four places that could have said so, and do not

1. `RowsLookback` has **no docstring**. Verified on `develop`: `data/lookback.py` gives it a
   validating `__post_init__` and nothing else. `CalendarLookback` documents only `lower_bound`.
2. `vqapr new datamodel --lookback N` emits `RowsLookback` unconditionally. **There is no flag that
   emits `CalendarLookback`**, so the scaffolded default is the wrong one for this entire class of
   model.
3. `SKILL.md` names neither class.
4. The one worked example in the scaffold consumes the batch in the exact per-instrument way that is
   safe for `RowsLookback` and silently wrong for a cross-sectional model.

`vqapr new --help` is the only surface that gets it right — *"rows of history each name needs"* —
and it is not what an author reads at the call site.

## The measured cost, since it is not only correctness

Same evaluation, both classes:

```
calendar  rows=477628  T= 323 sessions  N=1515  out=690  total=4.34s  load=3.84s
rows      rows=480202  T=1865 sessions  N=1562  out=690  total=4.84s  load=4.36s
```

`CalendarLookback` is ~10% faster and correct by construction rather than by the author's defensive
pivot. Under `RowsLookback`, about 1,250 of 1,562 names contributed nothing but rows that were
thrown away; over 2,096 daily evaluations that is most of a 2.7-hour run spent loading discarded
data.

## What would close it

A docstring on `RowsLookback`: *"the last N rows of each instrument independently; on an unbalanced
panel the batch's calendar span is set by the sparsest instrument"*. Plus a `--calendar-lookback`
form of the scaffold, or a scaffold that picks by model shape. Both classes are correct; only one of
them is reachable by following the package.
