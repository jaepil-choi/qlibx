# 093 — The fill table has a clock

**Closes:** `docs/issues/archive/022-the-fill-table-has-no-clock.md`, and resolves the unexplained half of
`docs/issues/archive/024`.
**Branch:** `fix/022-fill-envelope`.

## Why this change exists

The skill guarantees, without qualification:

> Every row of every table also carries the same five envelope fields: `run_id`, `producer_id`,
> `stage`, `event_time` and `sequence`.

`vqapr.account` had all five. The reporter's own diagnostic table had all five. **`vqapr.fill` had
none.**

It is the table this hurts most on, and the skill says so itself — *"This is the table cost
questions are asked of"*. A cost question with a date in it, *what did the 2022 rebalances cost?*,
could not be answered from this table at all, because no row said when it happened.

## The cause

`_fill_rows` builds its rows and they are staged **straight into the run-state chunks**
(`prepare_account_commit`), never passing through the `InvocationRecorder` that stamps the envelope
on every other table. Account rows go through a recorder and get all five automatically; fill rows
never touch one, so they got none. The asymmetry was structural rather than an omission in a list of
keys.

## What changed

- `_fill_rows` takes an optional `envelope` mapping and stamps it onto every row, numbering
  `sequence` per staged batch — the same contract `InvocationRecorder` uses, where
  `account_version` is what orders batches against each other.
- `prepare_account_commit` passes it through.
- The call site in `flow/simulation.py` supplies it from what it already holds: `run_id` from the
  frozen run identity, `producer_id` from the strategy component id, `stage` from the occurrence
  role, and **`event_time` from `pending.target.target_at`** — when the fill happened, not when the
  decision that caused it was made. Those are different instants and the envelope's own definition
  says `event_time` is the former.

The parameter is optional because callers with no occurrence in hand — the direct `AccountState`
constructors in the suite — have nothing truthful to stamp, and inventing an `event_time` is worse
than omitting one. Production always supplies it.

## This also closes 024's unexplained half

`docs/issues/archive/024` reported a per-table counter nobody could interpret: 7 for `ff3.formation` and
`vqapr.weight`, 85 for `vqapr.account`, and **1 for `vqapr.fill`** — *"which is the one that defeats
any reading I could construct, because 7 rebalances produced 13,012 fills across 7 distinct
instants"*.

`public.py:651` computes it as `len({str(row.get("event_time")) for row in rows})`. Fill rows carried
no `event_time`, so every lookup returned `None`, the set collapsed to one element, and the count was
1 regardless of how many instants the run actually had. Demonstrated directly: the same expression
over rows without `event_time` returns 1 for three fills across two instants, and returns 2 once the
field is present.

**No change to `public.py` was needed.** The counter was correct; the data it counted was missing.
This is exactly why the plan ordered 022 strictly before 024 — doing 024 first would have meant
writing an explanation for a number that was about to change.

## Validation

**Gate:** `test_all` (record shape) + `tests/flow/test_run_records.py` + `tests/flow/test_stamping.py`
+ `tests/qa/test_run_record_availability_clocks.py` +
`tests/flow/test_account_table_is_measurement_only.py`.

| check | result |
|---|---|
| the four named gate files | 26 passed |
| `tests/cli/test_krx_cost_journey.py` (slow, drives fills end to end) | 1 passed |
| **full suite, all marks** | **1384 passed, 0 failed**, 532.34s |

The merge condition's first half is asserted **on a real simulation** rather than on the row
builder: `test_fills_carry_the_five_envelope_fields_every_table_carries` runs a subprocess
simulation, reads the recorded `vqapr.fill` fields back, and requires all five by name. Its failure
message says what a reader loses per field, so a regression reports the consequence rather than a
missing string.

The second half — the counter reporting true distinct instants — follows from the first and was
verified against the counter's own expression.
