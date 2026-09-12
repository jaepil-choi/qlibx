# 126 — one lookback class

## Why this exists

`vqapr.authoring` and `vqapr.data.lookback` each defined a `RowsLookback` and a
`CalendarLookback`. The pairs were identical: same field names, same defaults, same validation
rules, same errors. `_internal/pit_bridge.engine_lookback` existed only to copy one into the
other, and said so itself:

> `authoring.RowsLookback` and `data.lookback.RowsLookback` are deliberately separate types: the
> authoring one is a public contract, the engine one is private. They carry the same economics,
> so this is a pure translation — it never widens a window or substitutes a different lookback
> kind.

Two names for one idea, plus a copy constructor to move between them, is the shape
`docs/vqapr-architecture.md` §4.4 rules out in one sentence — *"공유 항목의 해석 코드는 하나다"* —
and the smallest instance of the duplication `docs/issues/archive/036` was decided against on 2026-08-31.

## What changed

`vqapr.authoring` re-exports `data.lookback.RowsLookback` and `CalendarLookback` instead of
defining its own. `engine_lookback` is gone; `requirement_for` passes the declared lookback
straight through, so a declaration now carries the engine's object from the moment it is written.

**The engine's classes are the survivors, and the reason is what an author reads.** The engine's
`RowsLookback` carries the `docs/issues/archive/033` warning — that it counts rows **per instrument**, so a
sparse name reaches further back than a liquid one, and a cross-sectional model built on it is
*"well formed, non-null, passes every check, and is wrong"*. It names the measurement too: a
1,637-name universe with `rows=313` returned rows spanning 1,865 distinct sessions. The authoring
copy had a one-line docstring and none of that. The copy authors actually read was the copy that
did not warn them.

## What this costs an author

Nothing. Neither engine class is keyword-only, so `RowsLookback(rows=6)` and
`CalendarLookback(days=400, timezone="Asia/Seoul")` — the forms every call site in this repository
and all 54 in the research workspace already use — construct exactly as before, and
`vqapr.authoring.RowsLookback is vqapr.data.lookback.RowsLookback` is now simply true.

One test changed as a direct result. `test_rows_lookback_is_keyword_only_frozen_slotted` asserted
that `RowsLookback(3)` raises, because the authoring copy was `kw_only=True` and the engine's is
not. That refusal only ever existed because there were two classes; with one, asserting it would
pin a difference rather than a contract. Frozen and slotted are the properties worth keeping and
both survive.

## The test that predicted this

`tests/internal/test_pit_bridge.py` carried a guard whose docstring was a conditional:

> `test_the_public_and_engine_lookbacks_are_genuinely_distinct_types`
> *"If these ever became the same class the translation would be dead code."*

The condition came true, so the translation is dead code and is deleted. The assertion is kept and
**inverted** rather than removed: splitting the classes again would silently restore a translation
layer, and the first symptom would be a lookback that authored correctly and read as a different
window — which is exactly the failure mode issue 033 describes as passing every check.

## Validation

- `uv run pytest tests/ -q` — 1272 passed, 0 failed, on `develop@df331516`.
- `uv run ruff check src/` — clean.
- The deferred-import ceiling drops **41 → 37**: `engine_lookback` needed four function-local
  imports to name both sides of a translation that no longer exists.

## What this does not do

The declaration types themselves — `authoring.DatasetInput` versus `data.requirements.DataRequirement`
— are still two, and so are the two call surfaces (`call.read(alias)` versus
`context.window.observations(requirement)`). Those are the rest of the convergence
`docs/issues/archive/036` decided on, and the owner settled the direction on 2026-09-01: **the authoring
shape is the one to converge onto.** The work list is 036's own table, built by a first-time user
who had to construct it to get through the package.

`DatasetInput.dataset_id` **stays**. Removing it was briefly on the table while a field id was
going to be unique workspace-wide, but the owner overturned that half of `docs/issues/archive/049` on
2026-09-01: a field id is unique within a dataset, and a requirement names `(dataset_id, field_id)`.
