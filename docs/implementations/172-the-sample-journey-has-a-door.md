# 172 — The sample journey has a door: `vqapr new sample`, on synthetic data shipped in the wheel

**Closes:** PRD §11.4 ("explicitly materializable sample journey"), which record `170` had left as
a promise without an implementation. **Branch:** `develop`, on top of record `171`. **Owner
decisions, 2026-09-08:** commit the sample data to the repository and ship it in the wheel; make
it synthetic (company names twisted, prices rescaled) and say so; open it with `vqapr new sample
--out DIR`.

## Why

A first user had blank forms (`vqapr new strategy|dataset|execution-input|run` emit templates the
user fills with their own data) and no filled-in one: the sample that runs end to end lived under
`tests/` since record `170`, reachable by the suite alone. The owner's reading of what a sample
is for: a filled-in form beside the blank ones, so a first `register` / `check` / `run` happens
before anything is authored.

The obstacle was data. The panel was cut from a private KRX warehouse at every test session
(36 s, `data/DW`, absent on a user's machine) and could not be redistributed. The owner's
answer: *회사명을 적당히 바꾸고 가격 데이터도 적당히 바꾸면 돼. fake data라는 것을 밝히고 넣어주면
되는거지.* -- twist the names, rescale the prices, declare it fake, commit it, ship it.

## What was built

- **`scripts/build_sample_panel.py`** (developer-only): the builder record `170` had moved to
  `tests/sample/build.py`, now reading `data/DW` once and writing the synthetic panel into the
  package. Seeded (172). The transform: codes `K000001`..`K000010` in liquidity order; names
  with one syllable's vowel or one Latin letter changed (`삼숭전자`, `SK하으닉스`, `PXSCO`, ...);
  every price times a per-instrument scale in [1.5, 2.5] and a per-observation jitter of ±0.3 %
  (one jitter per name and session, so the execution close equals the observed close), so
  levels AND returns differ from the source; volumes scaled per instrument. Kept: 735 real KRX
  sessions 2022-01-03..2024-12-30, one name listing 200 sessions late, one stopping 250 early
  with a 3-session tradable wind-down.
- **`src/vqapr/agent/sample/`**: `reversal_5d.py` and `exchange.py` (back from `tests/sample/`),
  `data/` (`observations.parquet` 6,900 rows, `execution.parquet` 6,903, `instruments.csv`,
  `panel.json`, `README.md` stating the provenance), and **`materialize.py`**:
  `materialize(out_dir)` copies the two sources and the four data files and writes `sample.yaml`
  -- the one declaration with `datasets`, `execution_inputs`, `components` (the exchange with
  its `instruments` config) and `runs` (`sessions_from: sample-prices`, `start` on the second
  session, which is how the declaration says record `167`'s "the horizon opens on the second
  session") -- plus a README with the three next commands. About 275 KB in the wheel; `uv build`
  lists every file.
- **`vqapr new sample --out DIR`** (`cli/new.py`): calls `materialize`, refuses a non-empty
  directory (`argument.file_exists`, 409), and reports `declaration`, `run_id` and `next`: the
  three commands. Test: `tests/cli/test_new_sample.py` runs `new sample`, `register`, `check`
  through the CLI and asserts a clean check.
- **The suite installs the sample through the door.** `tests/sample/journey.py::install` is
  `materialize()` + `cli/register.run` on `sample.yaml`; `execute` freezes the registered run
  through the public door. The session-scoped `sample_panel` fixture, the warehouse dependence
  and the `real_data` marker are gone from the sample tests; the panel build no longer costs
  the suite anything.
- **The facade-boundary count is 3** again: `agent/sample/exchange.py` imports `vqapr.public`
  the way a user's venue does, and now a command copies it to the user. `docs/design/
  agent-first-surface.md` records 2 → 3.
- **`SKILL.md` Rung 1** opens with the sample: see one run happen before authoring, and copy
  its `sample.yaml` when writing your own declaration.

## What did not change

- The strategy, the venue, the run's shape and the expected counts the sample tests pin
  (1,468 occurrences, account version 729, run-state version 2,927): the reversal ranks names by
  five-day return, and rescaling with ±0.3 % jitter left every decision where it was. That the
  numbers held is a property of this transform on this panel, not a guarantee; the generator's
  seed is what makes it reproducible.
- No roster is registered for the sample (`instruments.csv` is a human-readable name table);
  the run's envelope keeps saying so, as it did.

## Trade-offs

- **Synthetic, not anonymised.** A per-instrument constant scale alone would have left the return
  series identical to the source; the jitter is what breaks reconstruction. The price of that is
  that the sample proves the shape of a run, not anything about a market -- the README, the
  skill and `panel.json` (`"synthetic": true`) all say so.
- **The generator needs the private warehouse.** It runs on the owner's machine only, once per
  change of the sample's shape; its output is what is reviewed and committed.
- **`tests/sample/build.py` is gone from the suite.** The panel's properties (ten names, the
  late lister, the wind-down tail) are asserted on the shipped files via `panel.json`.

## Validation

On the tree at the last commit of this record, 2026-09-08, alone on the machine:

- `uv run ruff check src/`: clean. `uv run vulture`: no output.
- `uv build`: the wheel lists `vqapr/agent/sample/data/{observations.parquet, execution.parquet,
  instruments.csv, panel.json, README.md}` beside the three modules.
- By hand, in an empty temporary directory with no `data/DW`: `vqapr new sample --out first-run`
  → `vqapr register first-run/sample.yaml` (components, dataset, execution input, run) →
  `vqapr check sample-run` (ok, nothing blocked or skipped) → `vqapr run sample-run` (6.8 s;
  1,468 occurrences, 1,997 fills dealt) → `vqapr show run sample-run`.
- `test_all` (`uv run pytest tests/ -q -m ""`): first run 1,475 passed, 3 failed -- the
  deferred-import ceiling (the sample import in `cli/new.py` was function-local; hoisted) and
  the per-kind `new` test that enumerates kinds (the `sample` kind declared) -- then rerun on
  the final tree: **1,479 passed in 334.8 s**, all eight showcases included. The suite is
  about a minute faster than record `171`'s 396.7 s: the panel build is gone.
- The sample-driven tests no longer build a panel: the slowest five are now the multi-strategy
  runs (21.6 s) and the showcase block (20.7 s); record `169`'s 52-55 s panel build is gone.
