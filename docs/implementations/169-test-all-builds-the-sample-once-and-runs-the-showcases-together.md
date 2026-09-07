# 169 — `test_all` builds the sample once and runs the showcases together

**Closes:** nothing tracked. Owner request, 2026-09-08: *the suite is what we run after adding a
feature or fixing a bug to see that nothing broke, so it must not take too long.* **Branch:**
`develop`, on top of records `167` and `168`. **Scope:** `tests/conftest.py`, nine tests that
install the sample, `tests/showcases/test_every_showcase_completes.py`, and one optional
parameter on `agent/sample/journey.install`. No runtime behaviour changed.

## What was measured

`uv run pytest tests/ -q -m "" --durations=80`, whole suite, before any change (this run shared
the machine with two showcase runs and a smaller suite, so its absolute numbers are inflated; the
shape is what matters):

| | seconds |
| --- | --- |
| whole suite, 1453 tests | 1931 |
| the twenty slowest tests, every one of which called `journey.install` | about 1650 |
| the eight showcases, one subprocess after another | about 90 |
| everything else | under 200 |

`journey.install` builds the sample panel from the `data/DW` warehouse CSV (about 36 s alone,
48-158 s under load) and then registers it. Nine test sites called it, each into its own project,
so the suite built the same read-only parquet nine times and ran the same 734-session sample
under twenty different assertions. The runtime itself was never the cost: the sample's 734
sessions execute in about 2 s (record `167`).

## What changed

- **`sample_panel`** (`tests/conftest.py`), session-scoped: builds the panel once into a session
  temporary directory, or skips when the warehouse is not provisioned. `journey.install` takes
  an optional `panel=` and registers it instead of building; a reader running the sample builds
  it exactly as before. The nine sites pass the session panel. The module fixture in
  `tests/agent/test_sample_panel.py` now returns the session one.
- **`showcase_outcomes`** (`tests/showcases/test_every_showcase_completes.py`), session-scoped:
  launches every collected showcase as a subprocess at once and waits for all of them; each
  parametrised test then reads its own outcome. The showcases are independent processes writing
  under their own `outputs/`, so the block now costs what the slowest showcase costs. Only the
  showcases the session collected are launched, so `-k show_006` still runs one.

## After

`uv run pytest tests/ -q -m "" --durations=25`, alone on the machine:

| | seconds |
| --- | --- |
| whole suite, 1453 passed | **375** |
| sample panel, built once (setup of the first test that asks) | 41 |
| `tests/acceptance/test_real_warehouse.py`, which reads the warehouse CSV to compare | 39 |
| eight showcases, launched together | 27 |
| the slowest sample-driven test after the change | 17 |

The previous complete runs of this suite in this session took 928 s (record `167`) and 1226 s
(record `168`, before the showcases were fixed), both alone on the machine.

## Not changed

- `tests/acceptance/test_real_warehouse.py` reads the warehouse on purpose: it proves the
  committed fixture still matches the source it was cut from. 39 s once per run is that proof's
  price.
- No `pytest-xdist`. The plan of record `167` excluded new dependencies, and the two changes
  above recovered the time without one; parallelising the whole suite would also have to answer
  for the tests that deliberately race processes on one record store.
- The default `test` command still deselects `slow`. What `slow` now costs is the panel build,
  the showcases and the sample-driven journeys, about four of the six minutes; `test` remains
  the iteration check and `test_all` the handoff gate.

## Validation

- `uv run ruff check src/` clean, and clean on every edited test file except one pre-existing
  long line in `tests/flow/test_a_run_reports_every_strategy.py` that this record did not touch.
- `test_all`: 1453 passed in 375 s, alone; the durations table above is from that run.
