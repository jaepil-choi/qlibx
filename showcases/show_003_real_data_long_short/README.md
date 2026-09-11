# show_003 — Real KRX data through the whole public chain

This showcase runs the documented public surface against the local `data/DW` warehouse. Every
price, trading session and tradability flag is real. No value is mocked, stubbed or hand-written.

## What it proves

1. **Real ingest and registration.** `scripts/extract_dw_fixture.py` slices the vendor CSV into one
   observation parquet and one exact execution parquet, then `register_dataset` and
   `register_dataset` (the venue table carries an `execution` role) validate and persist them.
2. **DataModel → derived dataset.** A 5-session cross-sectionally demeaned reversal score is
   computed per trading session and published through `materialize` as the registered dataset
   `reversal_score`, with per-invocation lineage.
3. **Strategy consumes the derived dataset.** The StrategyModel declares a `DataRequirement` on
   `reversal_score` — not on the raw prices — and builds its book from what it actually read.
   Intent source lineage is derived from real `ModelWindow` accesses, including the physical
   digest of the materialized parquet.
4. **Signed long/short execution.** The strategy emits a dollar-neutral complete portfolio
   (top-2 long at +0.25, bottom-2 short at −0.25, remainder 0) into a `SIGNED` Account, and
   `AcademicExchange` fills it at the exact selected close.
5. **Full lifecycle per rebalance.** Each session runs
   `ACCEPTED_INTENT → ACCOUNT_COMMITTED → MARKED → FEEDBACK_PUBLISHED`, then independent
   valuation and monitoring events, and the run finalizes with no pending intent.
6. **Independent accounting proof.** The run replays cash, positions and NAV from the published
   fill journal alone and asserts an exact match with the committed Account. A mismatch aborts.

## Timing contract exercised

- Observation and execution rows for a session share the venue close instant `15:30 KST`.
- The strategy callback is `08:30 KST`, so it can only ever see strictly prior sessions.
- `FillRule("close", "Asia/Seoul", at=15:30)` resolves one strictly-later execution target inside the run.
- Valuation `16:00` and monitoring `16:30` run on their own agendas.

## Honest limitations

- `AcademicExchange` is the zero-friction idealization: no commission, tax, slippage, borrow cost
  or market impact, and full fill at the selected close. Reported PnL is therefore signal PnL only.
- Listings declare `fractional_allowed=True`, so quantities are fractional. Integer lot sizing is a
  venue rule that belongs to a physical profile; no such profile is implemented yet.
- The signal is a deliberately naive reversal used to exercise the machinery. It is not a
  recommendation and its return says nothing about the framework's correctness.
- Short positions are hypothetical: no borrow, locate, collateral or margin model exists.
- The warehouse under `data/DW` is local vendor data and is not redistributed with this repository.

## Reproduce

```powershell
uv run python showcases/show_003_real_data_long_short/run.py
```

Inspect:

- `outputs/report.html` — human-readable evidence;
- `outputs/trace.json` — summary, universe, score sample, fills, lifecycle counts, replay proof;
- `outputs/inputs/fixture.json` — exact warehouse slice provenance;
- `outputs/project/.vqapr/materialized/reversal_score.parquet` — the derived dataset the strategy read;
- `outputs/project/.vqapr/workspace.yaml` — persisted declarations.

Requires the local warehouse at `data/DW`. Environment: repository `uv` environment, Python 3.12+,
DuckDB 1.5+.
