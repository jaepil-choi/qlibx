# show_007 — signal measurement, driven through a real run

A single price-derived alpha — a short-horizon reversal view, put on a common scale with `rank`,
neutralised against a market column of ones with `neutralize`, sized with `signal_weight`, and
matched to a small gross budget with `rescale` — runs through a real `run()` on committed KRX data.
Every event that computes a signal records the value *before* weighting (the ranked reversal)
and the value *after* neutralisation on a declared recorder table, so what a later reader consumes
is exactly what the callback saw, never a value reconstructed after the fact.

Reproduce:

```
uv run python showcases/show_007_signal_measurement/run.py
```

It reads `tests/fixtures/real`, so it runs on a clean checkout with no vendor warehouse.

## Why this showcase exists

The next milestone story's analysis functions read what a run stored. If those functions were
instead tested against hand-built rows, a defect in the transforms, the recorder, or the
publication path could hide behind a fixture that never went through the real spine. This showcase
is the thing that makes that impossible for the signal surface: every number the acceptance test
checks was produced by a real `StrategyModel.decide` callback, dispatched by a real
`SimulationFlow`, over real KOSPI 200 closes.

## What this demonstrates

| Claim | How it is shown |
|---|---|
| The signal transforms compose through a real callback | `rank` → `neutralize` → `signal_weight` → `rescale` all run inside `ReversalSignalStrategy.decide`, imported only from `vqapr.public` |
| The recorded signal is what the callback actually saw | `signal.measurement` records `signal_before_weighting` (the ranked view) and `neutralized_signal` on every event with enough history, written from inside the callback body rather than reconstructed afterward |
| A recorded diagnostic table round-trips through publication | `publish_run_record` publishes `signal.measurement` and the package-owned `vqapr.account` default table; both are read back from their published parquet — never from the producing run's own objects — and their row counts are checked against `result.final_state.recorder_rows` |
| The neutralisation is a real property, not an assumed one | The published signal table alone (not the transform, not the run) is used to recompute, on every event, that the neutralised signal sums to exactly zero against a market column of ones |
| A later reader can rebuild marks from rows alone | The published `vqapr.account` rows key into the run's own committed `mark_history`; every `Mark`/`MarkBatch` is rebuilt from `Decimal(str(...))` primitives and checked field-for-field equal to what the run actually committed — the seam the next milestone story depends on |
| The account is verified against its own journal | Cash and every position are rebuilt from the committed fill journal and compared to the committed `AccountSnapshot`; a mismatch aborts the run |
| Output is deterministic | The whole pipeline runs twice into separate projects, and both the reported outcome and the SHA-256 artifact digests must match |

## What this does NOT demonstrate

- **No cost model.** The run trades on the Academic exchange (fractional quantity, zero
  commission, zero tax, full fill). No KRX cost profile, whole-share rounding, or short-sale
  restriction is exercised here; `show_006` exercises the KRX profile.
- **This is a demonstration signal, not a claim of predictive value.** A demeaned-by-rank five-day
  reversal, neutralised and rescaled to a 2% gross active budget. It exists to be a real,
  non-degenerate, neutral signal on this fixture — not to be profitable.
- **No box, no compliance rules.** The run declares no `compliance`, and the strategy calls no kit
  function. Nothing here exercises `no_short`, `single_name_cap`, or any observation.
- **Mark rehydration is scoped to what a later callback actually witnessed.** A committed
  `AccountMark` is visible in the published `vqapr.account` series only if some later event's
  own callback ran and recorded having seen that account version; the run's *final* trade has no
  such later event, so its mark is legitimately absent from the published series and is
  excluded from the rehydration proof rather than silently skipped.
- **Four names are not two hundred.** The fixture is a four-constituent KOSPI 200 slice.
- **No warm-up trimming.** The signal needs six closes; earlier events on the schedule decline
  with `NoDecision` rather than being excluded from the callback calendar.

## Reading the signal evidence

`ReversalSignalStrategy` declares one recorder table, `signal.measurement`, with columns
`instrument`, `signal_before_weighting`, `neutralized_signal`. It is appended to on every event
with enough closes to compute a reversal view — including events whose neutralised signal
turned out flat and returned `NoDecision` — because a run that recorded only its trading events
would hide exactly the boundary the next milestone story needs to see. Reading that table back after
publication, rather than trusting the transform's own contract, is what makes the orthogonality
check in the acceptance test a real property of the artifact rather than a restatement of
`neutralize`'s own docstring.

## Results

Last verified 2026-08-18 against `vqapr-0.1.0+show-007-working-tree`, on the committed April 2026
KRX slice (22 sessions, 21 callbacks, 4 instruments).

| Metric | Value |
|---|---|
| signal events | 16 of 21 callbacks (five decline for want of a full six-close window) |
| signal_measurement rows published | 64 |
| vqapr.account rows published | 21 |
| rehydrated marks | 60 across 15 account versions, all field-for-field equal to committed |
| dealt fills | 64 |
| commission / sale tax | 0 / 0 (Academic exchange) |
| any short position marked | True (SIGNED account mode, no compliance rule) |

`outputs/` is gitignored, and each replicate builds its own project under it.
