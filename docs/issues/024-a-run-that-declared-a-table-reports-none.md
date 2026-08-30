# 024 — `run.complete` reports `tables_declared: []` for a run that declared and wrote one

**Status when filed:** open. Found 2026-08-30 by the final first-time-user journey in
`kwam-enhanced-index/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-008**,
`papercut`, and half of it left `unresolved`.
**Touches:** `src/vqapr/cli/run.py:491`, `src/vqapr/public.py:651`.

## The empty list

Reading the envelope of the successful run to confirm the diagnostic table had been recorded:

```json
{"ok": true, "stage": "run.complete", "account_version": 7, "occurrences": 99,
 "tables_declared": []}
```

`tables_declared` was expected to name `ff3.formation`, since declaring it is what made the run legal
at all (**019**). The table was written — `vqapr show run` reports 42 rows in it:

```json
"tables": {"ff3.formation": {"formations": 7, "rows": 42}, ...}
```

so the run envelope's `tables_declared` is the only place that disagrees. In this repository it is
built as `tables_declared=list(store.tables)` (`src/vqapr/cli/run.py:491`), which is where to start.

## The `formations` counter

The reporter could not work out what the per-table counter in `show run` counts. It is 7 for
`ff3.formation` and for `vqapr.weight` (7 rebalances), 85 for `vqapr.account` (85 valuation marks),
and **1** for `vqapr.fill` — *"which is the one that defeats any reading I could construct, because
7 rebalances produced 13,012 fills across 7 distinct instants."* `--help` does not mention the field
and neither does the skill. Marked `unresolved`.

**It is resolvable from the source, and the answer makes it a symptom of another issue.**
`src/vqapr/public.py:651` computes it as

```python
"formations": len({str(row.get("event_time")) for row in rows})
```

— the number of distinct `event_time` values. `vqapr.fill` rows carry no `event_time` at all
(**022**), so `row.get` returns `None` for every row and the set collapses to one. The counter is
correct for every table that has the envelope and meaningless for the one that does not.

So: fixing 022 fixes the `1`. This file still owns two things after that.

## What closes it

1. **`tables_declared`.** Either populate it, or remove it from the envelope — a field that is
   authoritative-looking and wrong is worse than a field that is absent, and `show run`'s `tables`
   map already answers the question correctly.
2. **Name the counter, or rename it.** "distinct event times" is what it counts; `formations` is
   what it is called. The word is also an unlucky collision in this journey — the reporter's own
   table is about Fama-French *formations*, and the field named `formations` counts something else.
   `occurrences` or `instants` would say it.

Neither is expensive. What makes them worth doing together is that a reader confirming a run wrote
what they asked it to write currently gets two disagreeing answers and one unexplained number, at
exactly the moment they are deciding whether to trust the artifact.
