# 084 — A lookback is measured where something reads

`check` refused a spec `run` completed. Same bytes, opposite answers:

```
$ vqapr check spec.yaml
{"ok": false, "failures": [{"code": "check.lookback.uncovered", ...}]}   exit 1

$ vqapr run spec.yaml
{"ok": true, "stage": "run.complete", "occurrences": 12}                 exit 0
```

The spec was this package's own end-to-end fixture. `check` was refusing the thing `run` was built
to demonstrate.

## The mirror of record 068, and worse

`068` was `check` returning `ok:true` on a spec `run` then refused. This is the other direction, and
the approved plan's Principle 5 names both — but the mirror is worse in a specific way: a user who
trusts `check` **stops here and starts editing a spec that already worked**. The verb exists to
prove a spec before a run is spent; a false refusal spends the user instead.

## Deciding which side was wrong, by measurement

Issue `012` deliberately did not guess, and named the two possibilities with opposite repairs:
either `run` was executing on short windows and its numbers were wrong, or the judgment was too
strict.

The fixture: three observations stamped `available_at` 03:00 on 03-05/06/07, a strategy agenda at
04:00, a lookback of two rows, and a run starting 03-05 00:00. What the run actually produced:

```
vqapr.weight: 2 rows
   2024-03-06T04:00  A  0.9
   2024-03-07T04:00  A  0.9
```

**The first occurrence produced nothing.** At 03-05 04:00 only one row was visible, the strategy
could not fill its declared lookback, and it returned `Hold` — the ordinary path the framework
already handles. Nothing was computed on a short window. The judgment was too strict.

## `start` is not an instant anything reads at

`start` bounds the horizon. The strategy reads at the occurrences its agenda generates inside that
horizon, and the earliest of those is what can be short.

The judgment compared the dataset's first observation against `start`, so it refused any spec whose
data begins after midnight — which is every intraday-stamped dataset. It measures at the first
decision now:

```
observed: dataset begins 2024-03-05 03:00:00+09:00, first decision 2024-03-06T04:00:00+09:00,
          lookback 2 row(s)
```

**T5B had already made this correction on the other side and it did not propagate.** The
materialization judgment written in record `076` measures at the earliest `evaluate_at`, not at a
horizon bound, because a materialization has no `start` to be tempted by. The simulation path was
left on the older comparison.

## It still bites

The repair is a change of reference point, not a relaxation. Verified with an agenda whose
`sessions:` place a decision on a day before the data exists:

```
observed: dataset begins 2024-03-05 03:00:00+09:00, first decision 2024-03-01T04:00:00+09:00,
          lookback 2 row(s)
```

Refused, as it should be. That case is unreachable through a `from_dataset` agenda, which only
generates occurrences on days the dataset has — so the judgment now fires exactly where a literal
session list outruns the data, and nowhere else.

`_first_decision` returns `None` when the agenda, the horizon or the ids are missing or
unresolvable. Those are other judgments' refusals to make; answering them here would report one
defect twice, and guessing an instant would put this verb straight back into refusing what `run`
accepts.

## The workaround came out with the defect

`test_a_constraint_registered_under_the_id_it_answers_to_still_runs` could not assert `ok:true` and
said so in a comment: it compared the constrained spec's failures against the unconstrained spec's
instead, because the fixture failed `check` either way. That comparison is gone. It asserts
`ok:true`, empty failures, empty blocked, and that every phase passed.

A workaround written down is a workaround that can be removed. It had been visible in the file for
exactly as long as the defect lasted.

## Validation

```
uv run pytest tests/ -q -m ""    # 1348 passed, clean
uv run pytest tests/ -q          # 1334 passed, 14 deselected
uv run ruff check src/vqapr/ tests/ showcases/   # 15, compared entry by entry: none introduced
```

`SIMULATION_CODES` is unchanged at eight — this moved a comparison, not the inventory. The
refusal-code baseline shows line movement only: nothing added, nothing removed.

`tests/cli/test_check.py::test_a_decision_that_lands_before_its_data_begins_is_named` asserts both
directions against the same registered dataset: a decision before the data is named, and a decision
the data covers is not — **even though `start` is still earlier than the dataset's first
observation in both**. That last clause is the fix, stated as an assertion.

`test_the_lookback_judgment_stays_silent_when_it_cannot_answer` pins the three shapes that cannot
be answered here, so a later change cannot turn "I do not know" back into a refusal.
