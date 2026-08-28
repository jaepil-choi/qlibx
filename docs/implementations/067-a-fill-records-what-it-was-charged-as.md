# 067 — A fill records what it was charged as

Two defects found by a first-time-user journey in `testbed/`, plus the suite speedup that journey
made unavoidable. Both defects were invisible to the whole test suite and visible within minutes of
using the CLI as a user does.

## The roster registered and changed nothing

Twelve instruments registered — ten `stock`, two `etf`, digest written to
`.vqapr/instruments.json` — and every one of 599 fills recorded `kind: None`. Byte-identical to the
run made before any roster existed. Registering a roster produced no observable difference
anywhere, which made the entire registration step unfalsifiable from outside.

**Two causes, and the first one I found was not the real one.**

I diagnosed it as a seam problem: `simulation.py` passed a bound view to `plan_orders`, while
`execute` read the venue's own unbound rules (`venue.py` off the `rules` property, `krx.py` off the
cached `_rules` field). That was real — record `065` claims *"a partial injection — one route
bound, the other not — cannot happen"*, and it could, and did. Fixed by binding the registry onto
the venue at run assembly rather than onto a view passed down, because `load_exchange` forbids
overriding `execute`, so its signature is not ours to extend.

**But the fills were still all `None` afterwards.** Instrumenting the run showed
`stamped_kind('A000011')` returning `etf` correctly at execution time. The value was reaching the
`Fill` and dying later: `vqapr.fill`'s `TableSpec` never declared a `kind` column, so `_fill_rows`
in `run_state.py` never wrote one.

Charging is a dictionary lookup at fill time and nothing downstream re-derives it, so the record
was the only place that fact could survive. Now:

```
{stock: 458, etf: 86, None: 55}
```

Every `None` is a zero-dealt `no_trade` — nothing was charged, so there is no category to record.
`None` stays legal for the same reason: a venue charging one flat rate needs no category, and a run
without a roster genuinely did not know.

**Why no test caught it.** The suite tests `Fill.kind` at the object level, where it was always
correct. Nothing asserted that the value reached the recorded row, because the column's absence
made that assertion impossible to write without noticing the absence. The journey noticed in one
command: it read the fill table.

## The instruments scaffold emitted two halves that disagreed

`vqapr new instruments --out roster.py` wrote a script that exported `instruments_stock.parquet`
and a declaration that named `roster_stock.parquet`. Registering failed every time.

The declaration derived its table names from the script's stem while `export_roster`'s `stem`
defaulted to `"instruments"`. They agreed only at the default `--out`, and `--out` is offered on
the same command. Fixed by having the emitted script pass its own stem.

`new exchange` and `new datamodel` both emit halves that work together, so this broke a pattern the
rest of the CLI keeps.

## Six minutes a check

The journey required running the suite repeatedly, which made the cost impossible to ignore: 452s
per check.

**`--durations` hid where it went.** The slowest reported calls were ~1.2s each — about 12s of
452s, which reads as "evenly slow" and invites the wrong fix. Summing by file instead:

```
264.7s   5 entries   tests/flow/test_run_freezes_its_record.py
 80.7s   6 entries   tests/agent/test_sample_panel.py
 49.1s   1 entry     tests/extension/test_scaffold_runs_unedited.py
------------------------------------------------------------------
395s of 475s = 83%, in thirteen end-to-end journeys
the other ~1,300 tests = 80s combined
```

Plus one 36s module fixture serving six tests that assert on its shape in milliseconds.

**Five of the thirteen were already marked `@pytest.mark.slow`.** The marker was declared in
`pyproject.toml`, enforced by `strict_markers`, and deselected nothing. The mechanism existed and
was not wired up.

Marked the other eight and made `-m 'not slow'` the default. **452s → 80s, 5.6x.** Nothing deleted,
nothing conditionally skipped: `-m slow` runs exactly those thirteen, `-m ""` runs all 1,311.

`.agent/project.yaml` now declares both — `test` for iterating, `test_all` before handoff — and
`AGENTS.md` says a change to run assembly, the record shape, or the emitted scaffolds is not
verified until `test_all` passes, because the slow thirteen are what cover those.

## Validation

- `uv run pytest tests/` — **1,298 passed, 13 deselected, 80s**.
- `uv run pytest tests/ -q -m ""` — **1,311 passed**.
- The testbed run that found the defect now reports `{stock: 458, etf: 86, None: 55}`, verified
  through the CLI as a user runs it.
- `vqapr new instruments --out roster.py` then `python roster.py` then
  `vqapr register roster.yaml` succeeds, verified end to end under a non-default name.
- Regression tests: `tests/cli/test_new_instruments.py` pins that the emitted halves agree under a
  custom `--out`; `tests/flow/test_account_table_is_measurement_only.py` pins that `vqapr.fill`
  declares `kind`.

## What this says about the suite

Both defects were in the gap between "the object is correct" and "the user sees it". The suite
tested the first and the journey tested the second, and only the journey found them. The one
mechanical check that did catch something — the per-category registration receipt catching a
silently dropped ETF table — works precisely because it fires on the success path.
