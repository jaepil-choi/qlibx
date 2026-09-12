# 101 — Both members of the lookback pair are reachable, and each says what it does

**Closes:** `docs/issues/archive/033-the-scaffolded-lookback-is-the-wrong-member-of-a-correct-pair.md`, and
the runnable half of `docs/issues/archive/030-the-skills-stop-condition-is-a-command-the-cli-refuses.md`.
**Branch:** `fix/033-the-lookback-pair-is-reachable`.

## Why this change exists

`RowsLookback` and `CalendarLookback` are a deliberate pair and the semantics are not in dispute.
What was wrong is that an author following the only path the package lays down arrives at the first
one and never learns the second exists:

1. `RowsLookback` had **no docstring**; `CalendarLookback` documented only `lower_bound`.
2. `vqapr new datamodel --lookback N` emitted `RowsLookback` unconditionally, with **no flag** for
   the other.
3. `SKILL.md` named neither class.
4. The one worked example consumes the batch per instrument — safe under a rows lookback, and the
   exact pattern that is wrong under it for a cross-sectional model.

The cost is not aesthetic, and it was measured rather than argued. A rows lookback returns each
name's **own** last N observations, so the batch is a union of per-instrument tails and its calendar
span is set by the sparsest name, unbounded above. A first materialization over 1,637 names with
`rows=313` returned rows spanning **1,865 distinct sessions**, back to roughly 2016. Consumed the
scaffold's way, a 2024 correlation matrix then mixes a liquid name's 2023-24 returns with a name
that delisted in 2019 — well-formed, non-null, passes every check, and wrong. The reporter avoided
shipping it by habit, pivoting on each row's own `available_at`, and had misread the 872 names they
dropped as delistings rather than time-misalignment.

Same evaluation, both members: `calendar` gave 323 sessions and `rows` gave 1,865, for the same 690
usable names, with the calendar form ~10% faster because the row form loaded rows the model then
discarded.

## What changed

- **`RowsLookback` has a docstring** stating per-name, per-field counting, the unbounded calendar
  span with the measured numbers, which questions it is right for, and which member to use instead.
  `CalendarLookback` states the shared window and that its unit is calendar days, not sessions.
- **`vqapr new datamodel --calendar-lookback DAYS`** emits the other member. It is a real second
  flavour, not a substituted class: the emitted file imports `CalendarLookback`, declares
  `LOOKBACK_DAYS` and `TIMEZONE`, and its completeness guard is `len(values) >= 2` rather than
  `len(values) == LOOKBACK`, because a calendar window promises no row count.
- **Both flavours carry a note** in `compute` saying what their window is and, for the rows form,
  naming `--calendar-lookback` as what a cross-sectional model wants. The scaffold is where an
  author is standing when the choice is made.
- **`--lookback` and `--calendar-lookback` together are refused**, rather than resolved by
  precedence a reader would have to know. `--calendar-lookback` on a strategy is refused with the
  reason: that template's signal counts observations per name, so a day count would leave its guard
  meaningless.
- **`SKILL.md` names the pair**, states the span property, and says which member each kind of model
  wants.

**One template, four substitutions** — class, declaration, requirement expression, guard — rather
than a second copy of a forty-line file that would drift. What differs between the two is exactly
what an author has to understand.

## Also closed here: `docs/issues/archive/030`, the runnable half

Rung 1's stop condition read *"`vqapr list` shows all required elements"*. `kind` is a required
positional with no all-kinds form, so the first command of a first-time journey returned
`cli.usage.rejected`. The sentence now names one call per kind for the seven a Rung 1 setup
creates, names the other three, and says there is no all-kinds form so the refusal is predicted
rather than discovered.

`tests/cli/test_the_stop_condition_is_runnable.py` keeps the two in step: every kind the skill names
must be in `list_.KINDS`, every member of `KINDS` must appear in the block, and bare `vqapr list`
must still be refused — if `list` ever grows the all-kinds form the issue argues is the better
shape, that test fails and the skill goes back to one sentence in the same commit.

**The second half of 030 is left open on purpose**: whether `cli.usage` refusals fall inside the
six-field envelope guarantee (they carry three) is a decision about what that guarantee covers.

## Validation

| check | result |
|---|---|
| `tests/extension/test_the_scaffold_offers_both_lookbacks.py` (new) | 7 passed |
| `tests/cli/test_the_stop_condition_is_runnable.py` (new) | 4 passed |
| `tests/extension/`, `tests/cli/` | 307 passed |
| fast suite | **1435 passed**, 14 deselected |
| `-m slow` | **14 of 14 passed** |

The calendar scaffold is held to the same gate as the rows one — **it must run as written**. The new
test emits it, registers it, loads it and calls `compute` against a real parquet, asserting the
derived values rather than the file's shape: three calendar days back from 2024-03-07 16:00 KST
gives both names their 03-05..03-07 rows, so A returns `0.05` and B returns `0.06`.
