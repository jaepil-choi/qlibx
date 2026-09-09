# 2026-09-03 -- scenario testbed run 2: FINDINGS.md as handed over

**What this is.** A verbatim copy of `kaist-thesis/vqapr-scenario-testbed/FINDINGS.md` at the end
of run 2, kept here because that file is gitignored in the testbed by design (a committed
FINDINGS would hand the next agent the previous agent's answers). Protocol step 6 of the testbed's
`README.md` says to keep the copy upstream; run 1's copy is `2026-08-30-final-testbed-findings.md`.

**The run.** Wheel `vqapr-0.3.0` (`develop @ 4f616f5a`). Scenario: the paper's PCA-residual arm on
Korean daily equities, amended live to FF5+MOM (K = 6) OU+Thresh (phase 1), then K = 0 / K = 5 x
OU+Thresh / Fourier+FFN plus a cProfile of one strategy (phase 2). Everything asked for was
delivered inside the package; nothing was `blocked`.

**Triage outcome.** 17 findings. 14 filed as `docs/issues/archive/055`-`068` (the mapping is under each
entry below, written into the file by the evaluator). Not filed: F-003 (console encoding, agreed
`No`); F-015 (same root as F-013 / `061`, its numbers attached there). Closed the same day by the
deletion campaign: `058` (record `146`, F-008) and `061` (record `143`, F-013 / F-015); of the
Known issues the agent was handed, `053` and `054` were closed by records `141` and `142`. The
index is `docs/issues/README.md` section 1.

---

# FINDINGS.md — vqapr-scenario-testbed

<!-- EVALUATOR: fill the three fields below and the Known issues section before the agent starts.
     This file is gitignored. See README.md, Protocol step 0. -->

| | |
|---|---|
| **Wheel** | `vqapr-0.3.0-py3-none-any.whl` — built 2026-09-03 from `qlibx@develop@4f616f5a` (tag `v0.3.0`) |
| **Skill** | `.agents/skills/vqapr/SKILL.md`, installed by `vqapr skill install --into .` |
| **Scenario** | given live / `SCENARIO.md` |
| **CLI verbs at this wheel** | eight: `new` `register` `check` `run` `list` `show` `rm` `skill` |

## Known issues

<!-- EVALUATOR: list the ../../qlibx/docs/issues/ entries still open against this wheel, one line
     each: `- **NNN** — title`. The agent annotates under a line when one costs it time; it does not
     re-file them. An empty list is a valid list; do not pad it. -->

- **023** — a run's record carries a digest of every source file it read, but nothing compares it
  to what is registered now. If a parquet is overwritten in place after registration, no command
  says so. Workaround: if provenance matters, compare the digests in the run record yourself.
- **027** — registering a dataset never asks which point-in-time convention your `available_at`
  column follows. A value stamped "the date at midnight" and one stamped "when it became knowable"
  both register fine and mean different things. Workaround: decide the convention yourself before
  registering, write it down, and stamp `available_at` at the instant the value was knowable.
  - *This run:* cost about ten minutes of design time, not because the convention was hard to pick (close = 15:30 KST) but because the paper's "trade at the close on the close's information" then has no honest instant to fill at; see F-010.
- **053** — on a dataset registered with `grain: rows`, `InstantsLookback(n)` hands your model
  the last *n rows* per name, not the last n instants. If a name has several rows at one instant,
  you get fewer instants than n and nothing says so. Workaround: declare a larger n and select in
  the model, or register the table at a panel grain with one expression per value you need.
  - *Upstream 2026-09-03:* **closed by record `141`** (`InstantsLookback(n)` now counts instants). Not in this wheel.
- **054** — reading a `grain: rows` dataset is slow, and the time is not in the query: most of it is
  spent building the rows handed to your model. Workaround: prefer a panel grain with expression
  fields for anything cross-sectional; keep `rows`-grain reads narrow.
  - *Upstream 2026-09-03:* **closed by record `142`** (framework-built rows are not revalidated; 6.68s → 2.10s on 80 names). Not in this wheel.
- **052** — not user-facing: nothing in the package's own test suite runs its showcases. Listed so
  the open set is exact.

Two papercuts without an issue file: `--out /dev/null` on Windows creates a file named `nul.py`;
a StrategyModel class built with `type()` is refused with a message that names module `abc` and
points nowhere.

## Findings

<!-- AGENT: write entries here as they happen, in the format AGENTS.md gives. F-001 first. -->

> **Evaluator triage, 2026-09-03 (phase 1 entries F-001–F-014).** Each `Yes`/`Unsure` entry was
> re-checked against the `qlibx` source before filing. Twelve are filed upstream as
> `qlibx/docs/issues/archive/055`–`066`; the mapping is written under each entry below. Not filed: F-003
> (console encoding, `No`). The `027` annotation above is kept as evidence on that issue.
>
> **Second triage, 2026-09-03 (phase 2 entries F-015–F-017).** F-017 filed as `067`, F-016 as
> `068`; F-015 is the same root as F-013 (`061`), which `qlibx` record `143` has since closed, so
> its profile numbers were attached to `061` rather than filed again. Upstream has also closed
> `054` (record `142`) and `058` (record `146`, F-008) since the first triage.

### F-001 — `Hold(reason=...)`: skill says one token no spaces, docstring says spaces are allowed

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/062`. Confirmed: `SKILL.md:429` vs `authoring.py:467`; the docstring is the true rule (record 125).

**Severity:** papercut
**Kind:** docs
**Attributable to vqapr?** Yes — two shipped documents on the same wheel state opposite rules for the same argument.
**Resolved by:** unresolved (will test which is true when the strategy first returns `Hold`)
**Where:** `.agents/skills/vqapr/SKILL.md` ("Return `Hold(reason=...)` to decline. The reason is one token, no spaces.") vs `help(va.Hold)` ("a reason a human reads should be allowed spaces")
**What I was trying to say:** I wanted to know how to write a decline reason before writing the strategy.
**What happened:** the skill and the docstring contradict each other. The scaffold hedges with `reason="no-name-scored-above-zero"`, hyphenated, which is consistent with the stricter rule and so does not settle it.
**What would have told me directly:** one rule in both places, or the skill line removed since the docstring is the closer source.

### F-002 — `vqapr new strategy --dataset residuals --field resid` names the alias `prices` and the docstring "Ranks the cross-section"

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/063`. Confirmed in the scaffold template.

**Severity:** papercut
**Kind:** docs
**Attributable to vqapr?** Yes — the scaffold takes the dataset and field name but the emitted code still calls the read `"prices"` and describes a long-only momentum ranker regardless.
**Resolved by:** surface (renamed the alias by hand)
**Where:** `vqapr new strategy ou-thresh --dataset residuals --field resid --lookback 30`
**What I was trying to say:** scaffold a strategy that reads a residual dataset.
**What happened:** the emitted `inputs()` returns `{"prices": read}` and `decide()` calls `call.read("prices", "resid")`. Harmless, but a first-timer reads `prices` as a required alias name for a moment.
**What would have told me directly:** the alias derived from `--dataset` (`{"residuals": read}`), or a comment saying the alias is free-form.

### F-003 — Windows console: `help()` output with em-dashes crashes on cp949, needs `PYTHONIOENCODING=utf-8`

> **Evaluator 2026-09-03:** not filed; agreed `No`.

**Severity:** papercut
**Kind:** docs
**Attributable to vqapr?** No — my Windows console encoding; the docstrings are fine.
**Resolved by:** guess (set `PYTHONIOENCODING=utf-8`)
**Where:** `pydoc.render_doc(va.DataRequirement)` printed to a cp949 stdout
**What I was trying to say:** read the docstrings of the authoring surface.
**What happened:** `UnicodeEncodeError: 'cp949' codec can't encode character '—'`.
**What would have told me directly:** nothing vqapr owes here.


### F-004 — ran `vqapr register` from a subdirectory; a second workspace appeared silently and the next refusal named the missing datasets but not the workspace it looked in

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/066`, as a message defect (`Unsure` → `Yes`). `Workspace.create` never looks at parent directories and no envelope carries `workspace_root`.

**Severity:** slowed
**Kind:** message
**Attributable to vqapr?** Unsure — `vqapr --help` does say the workspace root defaults to the current directory, so the trap is documented; but the refusal `unregistered: kr-daily, kr-factors` with fix `register the missing datasets` would have led me to register duplicates into the wrong root, and nothing in the payload names which `.vqapr` was consulted.
**Resolved by:** guess (noticed `work/decl/.vqapr/diagnostics` in the `detail` path, deleted that workspace, re-ran from the project root)
**Where:** `vqapr register ff6_resid.yaml` then `vqapr check mat_smoke.yaml`, both run with cwd `work/decl/`
**What I was trying to say:** register the DataModel into the workspace where the datasets already live.
**What happened:** `register` succeeded (into a fresh `work/decl/.vqapr`), then `check` said `every dataset the model declares it reads must be registered / unregistered: kr-daily, kr-factors`. The datasets were registered five minutes earlier, from the project root.
**What would have told me directly:** the refusal (or every command's envelope) carrying `workspace_root: <path>`; or `register` warning when it creates a brand-new workspace while a parent directory already holds one.

### F-005 — `vqapr show model` lists the same dataset id once per field under `decides`, and `records: []` for a strategy whose `tables()` declares a table

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/055`. Confirmed and worse than reported: `show model` reads attributes (`_aliases`, `_authored_tables`) that no code sets, so `reads` is empty for every model.

**Severity:** papercut
**Kind:** code
**Attributable to vqapr?** Yes — the output is the package's own description of a component it just accepted; a field-level fan-out shown as seven identical dataset ids and an empty `records` next to a declared `TableSpec` misdescribe the component.
**Resolved by:** surface (ignored; the dev run did write `ou_summary`, so `records: []` is a display defect of `show model`, not a contract one)
**Where:** `vqapr show model ou-thresh-ff6`
**What I was trying to say:** confirm what the strategy reads and which table it will record before running.
**What happened:** `"decides": ["ff6-resid-values" x7, "kr-daily"], "reads": {}, "records": [], "forms": []`. The skill says `show model` describes "what a component declares it reads, decides, forms, weights and records"; `reads` is empty although eight fields are declared, and `records` is empty although `tables()` returns one `TableSpec`.
**What would have told me directly:** `reads` as `{alias: {dataset, fields, lookback}}`, and `records` listing the declared table ids.

### F-006 — `vqapr check <run>` reports one missing dataset seven times, once per field the strategy reads from it

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/056`. Confirmed: the judgment loop is per requirement (= per field) with no grouping by dataset.

**Severity:** papercut
**Kind:** message
**Attributable to vqapr?** Yes — the same `check.dataset.unregistered` failure with identical `requirement`, `observed`, `fix` and `source` is emitted seven times (the strategy reads seven fields of `ff6-resid-values`), plus an eighth `workspace.dataset.lookup.missing` for the same dataset. Eight entries, one defect.
**Resolved by:** surface (the dataset simply was not materialized yet; waited)
**Where:** `vqapr check ff6-ou-thresh` before the materialization that produces `ff6-resid-values` had finished
**What I was trying to say:** confirm the run is ready.
**What happened:** the envelope's `failures` list had eight entries for one missing dataset. The skill promises `check` reports "every INDEPENDENT problem at once"; these are not independent.
**What would have told me directly:** one failure per (dataset) with the fields listed inside it.

### F-007 — `read_strategy_table(<wrong root>, ...)` returns an empty iterator instead of refusing

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/057` (together with F-012). Confirmed: `read_table` returns silently on a missing path, and `strategy_ref=None` resolves to a record shape a 0.3.0 run never writes.

**Severity:** slowed
**Kind:** message
**Attributable to vqapr?** Yes — the skill documents the call as `read_strategy_table(store_root, run_id, table, strategy_ref)` and `vqapr run --store-root` says the default is "the workspace directory", so I passed the project root; the rows live under `<root>/.vqapr/runs/...` and the reader silently found nothing.
**Resolved by:** guess (the run result's `store_root` field says `...\.vqapr`; passing that worked)
**Where:** `vqapr.public.read_strategy_table(ROOT, "ff6-ou-thresh-dev", "vqapr.account", None)`
**What I was trying to say:** read the NAV series of a finished run from Python.
**What happened:** three empty DataFrames and an AttributeError downstream in my own code. No refusal, no "no such run under <path>". Probing nine (root, strategy_ref) combinations showed rows come back **only** for root `.vqapr` **and** the full `<strategy-id>@<fp8>` ref; `strategy_ref=None` (which the signature types as allowed) and the bare `<strategy-id>` form (which the CLI accepts when one record exists) both return an empty iterator with no message.
**What would have told me directly:** a refusal naming the directory it looked in and the run ids it found there; or the docstring/skill saying the root is the `.vqapr` directory, consistently with what `vqapr run` prints as `store_root`.

### F-008 — recorded `event_time` is printed with `+09:00` in `vqapr.account` rows and `+00:00` in `vqapr.fill` rows of the same strategy

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/058` (`Unsure` → `Yes`, code). Confirmed: the execution table converts the fill target to UTC; agenda-stamped rows keep the declared zone.
> **Fixed upstream 2026-09-03:** `058` closed by record `146` — the fill row's `event_time` is stamped in the strategy agenda's zone, and record tables are parquet so the zone travels in the column type. Lands in the next wheel.

**Severity:** papercut
**Kind:** message
**Attributable to vqapr?** Unsure — both are correct instants, but a reader eyeballing `show strategy --table` sees two clocks for one run and has to convert before comparing rows across tables.
**Resolved by:** surface (converted everything to Asia/Seoul myself)
**Where:** `vqapr show strategy ff6-ou-thresh-dev/ou-thresh-ff6-dev --table vqapr.account` vs `--table vqapr.fill`
**What I was trying to say:** line a fill up against the valuation that followed it.
**What happened:** `"event_time": "2016-12-16T15:40:00+09:00"` on the account row, `"event_time": "2016-12-16T06:35:00+00:00"` on the fill row.
**What would have told me directly:** one offset convention for every recorded instant (the venue's, or UTC, but the same one).

### F-009 — a 2,378-session materialization wrote a 478 MB lineage JSON, held ~3 GB of RAM, and took 20 minutes, with no progress output

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/059`. Confirmed: rows and per-evaluation access records are accumulated in two lists and written after the loop; lineage repeats every instrument per evaluation. Both 477–478 MB lineage files in `.vqapr/materialized/` are the evidence.

**Severity:** slowed
**Kind:** code
**Attributable to vqapr?** Yes — the per-invocation `accesses.actual_rows` block repeats every instrument's row count for every evaluation (2,145 names x 2,378 evaluations), which is where the 478 MB goes; all rows and lineage appear to be held in memory until the end (python RSS ~3 GB at 17 minutes for a 205 MB parquet output); and `vqapr run <spec>` prints nothing until it finishes, so for 20 minutes the only way to tell "running" from "hung" was the process list.
**Resolved by:** surface (it finished)
**Where:** `vqapr run work/decl/mat_full.yaml` (DataModel `ff6-resid`, 2,145 instruments, 2,378 `evaluate_at`)
**What I was trying to say:** materialize daily residuals for the whole sample.
**What happened:** 19m53s wall clock; the 13-evaluation timing run had suggested ~0.45 s per evaluation plus ~32 s fixed, i.e. ~18 minutes, so throughput was as measured, but the memory profile is a risk on the machine this scenario is meant for (the user dropped the PCA arm because of memory on another box). Lineage for 45 evaluations was already 9 MB.
**What would have told me directly:** a progress line per N evaluations (or `--progress`); lineage that records access counts once per instrument per distinct value rather than per evaluation, or at least compressed; rows streamed to the parquet as they are produced.

### F-010 — the paper's "decide on the close, trade at that close" cannot be stated; I had to invent a 15:35 fill five minutes after a 15:30 close

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/064` (`Unsure` → `Yes`, docs). The agendas template presents the one-session-lag convention as the correct one and names no other; this is the entry the testbed exists for.

**Severity:** slowed
**Kind:** docs
**Attributable to vqapr?** Unsure — the rule (fill strictly later than the callback, callback sees only strictly-earlier data) is a sound point-in-time discipline and is documented in the agendas template; but the standard academic convention of "rebalance at close t using information through close t" is the one every daily-frequency paper uses, and the only way to express it is to stamp fictitious instants (data 15:30, materialize 15:31, decide 15:32, fill 15:35, value 15:40), which nothing in the surface suggests or blesses.
**Resolved by:** guess (the fiction works; the run's returns line up with the paper's timing exactly)
**Where:** `agendas.yaml` `at:`, `execution-input.yaml` `fill.at`, `mat_full.yaml` `evaluate_at`
**What I was trying to say:** "the position set from residuals through close t earns the return from close t to close t+1."
**What happened:** the scaffold's own example (callback 15:29, fill 15:30) lags the decision a full session behind the data, which for a 30-day mean-reversion signal is a different strategy (see the lag-2 diagnostic in `out/REPORT.md`: one session of misalignment moves the Sharpe ratio by 0.6). I had to work out the fictitious-instant scheme myself and prove it with an independent residual recomputation.
**What would have told me directly:** one paragraph in the skill or the agendas template: "to trade at the close on the close's own data, stamp the data at the close and put the callback and fill a few minutes after it, in that order", ideally with a `same_close` fill selector that says it in one word.

### F-011 — `vqapr rm` has no `dataset` kind, so a materialized dataset can never be withdrawn

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/060`. Confirmed: eight `rm` kinds, none of them `dataset`; the skill line promising the removal is `SKILL.md:157`.

**Severity:** papercut
**Kind:** code
**Attributable to vqapr?** Yes — the skill says "to replace an output, remove its dataset registration first", and no verb removes one: `rm` offers run, strategy, component, agenda, strategy-config, valuation-config, monitoring-policy, run-definition.
**Resolved by:** unresolved (three throw-away datasets — `ff6-resid-smoke`, `ff6-resid-timing`, `ff6-resid-dev` — stay registered; had the full materialization failed half-way I would have had to pick a new id)
**Where:** `vqapr rm --help`
**What I was trying to say:** clean up the smoke-test outputs, and have a way to re-materialize under the same id after a fix.
**What happened:** nothing to try.
**What would have told me directly:** `vqapr rm dataset <id>` (refusing while a run record reads it), or the skill not promising a removal that does not exist.

### F-012 — urge: when `read_strategy_table` returned nothing I wanted to open `vqapr/flow/run_records.py` to see how it resolves the root

> **Filed upstream 2026-09-03:** folded into `qlibx/docs/issues/archive/057` with F-007.

**Severity:** urge
**Kind:** docs
**Attributable to vqapr?** Yes — the reader has two undocumented conventions (root is `.vqapr`, ref must carry the fingerprint) and fails silently on both; that is exactly the situation where a user reaches for the source.
**Resolved by:** guess (probed nine root × ref combinations instead; F-007)
**Where:** `vqapr.public.read_strategy_table`
**What I was trying to say:** which directory does it look in, and what does `strategy_ref=None` mean.
**What happened:** the docstring (`read_typed_table(root, run_id, table_id, strategy_ref=None)`) names the arguments but not the root convention, and the skill's `store_root` contradicts `vqapr run`'s printed `store_root`. I did not open the source.
**What would have told me directly:** the docstring saying "root is the store root `vqapr run` prints (`<project>/.vqapr`); `strategy_ref` is `<strategy-id>@<fp8>` as `vqapr list strategies --run` prints it", and a refusal when the path does not exist.

### F-013 — `window.values[name][-30:]` costs exactly as much as reading the whole 1,030-row column; there is no cheap "last n" on a long lookback

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/061` (`Unsure` → `Yes`, code). Confirmed and worse than measured: `values` builds every name's column on each access, so `values[name]` is the whole panel, then one column.
> **Fixed upstream 2026-09-03:** `061` closed by record `143` — `values` is a lazy mapping (`values[name]` converts one column), `latest()` and `counts()` stay in Arrow, and the docstring states the cost. No `tail(n)`. Lands in the next wheel.

**Severity:** slowed
**Kind:** docs
**Attributable to vqapr?** Unsure — `PanelWindow` says it is "a 2d slice, not a copy", which is true of the window, but `values[name]` builds the full per-name tuple on access, so a model that declares a 1,030-row lookback (because it retrains every 125 sessions on 1,000 days) pays ~0.3 s per callback for 2.2 M cells even on the 124 sessions where it only wants the last 30. Nothing documents the cost, and a probe was the only way to learn it.
**Resolved by:** guess (measured with a probe strategy; then restructured the strategy to read the full history only on retraining days and use `latest()` otherwise). *Superseded by F-015:* the 0.3 s was not tuple materialisation, it was `values` being rebuilt for every name because I indexed `window.values[name]` inside a loop.
**Where:** `call.read("resid", "resid").values[name]` with `RowsLookback(rows=1030)` (`work/decl/probe_lookback.py`, log in `probe_lookback.log`)
**What I was trying to say:** "give me the last 30 residuals per name today, and the last 1,030 on the days I retrain."
**What happened:** read 0.09 s, iterating every column 0.31 s, slicing the last 30 of every column 0.31 s, first callback 30 s (panel build). Fine in absolute terms (~15 min over a run) but invisible until measured, and on a 2 x 2 grid of strategies it is an hour.
**What would have told me directly:** a `window.tail(n)` / `values_tail(name, n)` accessor, or one sentence in the `PanelWindow` docstring saying `values[name]` materialises the column and that two `DatasetInput`s with different lookbacks are the way to have a cheap daily read and an expensive periodic one.
**Post-profile correction (attributable: Yes):** with F-015 fixed, the long lookback still costs the package ~480 s of a 1,918 s `fft-k0` run: `panel.py:214 counts` visits every cell of the declared window on every `read` (442 M generator steps + 234 s in `sum`) to fill the access record's per-name `actual_rows`, whether or not the model looks at those cells. A 1,030-row window read 2,698 times is 5 billion cells counted for a bookkeeping field. The cost is per read and O(window), so it cannot be avoided from the model side except by declaring a short lookback — which a model that retrains on 1,000 days cannot do. Counting once per window per name from the panel's null mask (or lazily) would remove it. On `fft-k5` (six fields x 1,030 rows) the same bookkeeping was 864 s in the generator plus 769 s in `sum` plus 384 s in `series` of a 3,599 s run — more than half the wall clock, and the generator's call counter overflowed a signed 32-bit int (`-1404558399 calls` in pstats), i.e. more than 2.1 billion cell visits.

### F-014 — a 2 x 2 grid (two signals x two residual sets) needed four near-identical strategy files because a component's `inputs()` cannot be parametrised from the run

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/065`. Confirmed: preflight and orchestration both call `requirements()` before `memory` is assigned, so the safe reading was right; the design question (class + config under one id) is attached to the issue.

**Severity:** slowed
**Kind:** docs
**Attributable to vqapr?** Yes — `vqapr new run` shows `initial_model_memory: {}` per strategy and `show strategy` records a `config: {}`, so a per-strategy configuration channel exists, but nothing says whether `inputs()` may depend on it (memory is restored "before every decide()", not before `inputs()`), and a file "must define exactly one StrategyModel subclass". The safe reading was code generation from a template.
**Resolved by:** guess (`work/decl/strategy_template.py` + a generator wrote `ou_k0.py`, `ou_k5.py`, `fft_k0.py`, `fft_k5.py`, differing in four constants)
**Where:** registering `ou-k0`, `ou-k5`, `fft-k0`, `fft-k5` for run `arb-k0k5`
**What I was trying to say:** "same strategy, four (dataset, signal) settings, one run."
**What happened:** four registrations, four fingerprints, four copies of 200 lines to keep in step.
**What would have told me directly:** the skill saying whether `config`/`initial_model_memory` reaches `inputs()` (and if not, that a template is the intended pattern), with an example of one class registered under several ids with different configs.

### F-015 — `PanelWindow.values` rebuilds every column on each access; `window.values[name]` inside a loop over names is O(N²) and was 82% of a strategy run

> **Evaluator 2026-09-03:** same root as F-013 → `qlibx/docs/issues/archive/061`, **closed by record 143** (`values` is a lazy mapping; `values[name]` converts one column). The profile numbers here are attached to `061` as evidence. Not filed separately.

**Severity:** slowed
**Kind:** code
**Attributable to vqapr?** Yes — `values` is documented as "Every column of the window, keyed by instrument", reads like a dict attribute, and the scaffold itself writes `for name in window.instruments: ... window.values[name]`; but it is a property that builds a fresh mapping of all N columns on every access, so the scaffold's own idiom costs N × N column builds per callback. cProfile on `ou-k0` (1,349 sessions, 2,151 names): `panel.py:197 values` 2,901,699 calls, 1,910 s cumulative of 2,326 s total; `panel.py:181 series` 1,955,292,350 calls. The strategy's own arithmetic was 38 s.
**Resolved by:** guess (profiled the whole process with cProfile; bind `vals = window.values` once per callback and index that)
**Where:** every `call.read(...).values[name]` in `ou_thresh.py`, the four `*_k0.py`/`*_k5.py` strategies and `probe_lookback.py`; the idiom comes from `vqapr new strategy`'s scaffold
**What I was trying to say:** "give me this name's column."
**What happened:** the 16-minute K = 6 run and the 38-minute profiled `ou-k0` run were almost entirely this; the Fourier strategies, which read 1,030-row windows, would have spent about an hour per retraining day in it.
**What would have told me directly:** `values` cached (a `functools.cached_property`, or computed once in `__post_init__`), or `series(name)` promoted in the scaffold as the per-name accessor with `values` documented as "builds all columns; bind it once".

### F-016 — where the rest of a strategy session goes, from the same profile (for the maintainer, not a defect)

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/068`. Filed as a defect after all: the two per-session execution snapshots are fetched row by row as Python datetimes (the `pytz`/`replace` lines), the shape `054`/`061` closed elsewhere; `counts` and `run_records.append` are already changed by records `143`/`146`. The per-phase timing request is in the same issue.

**Severity:** papercut
**Kind:** code
**Attributable to vqapr?** Yes — package-side costs per session after removing F-015: `scan.py:630 exact_snapshot_rows` 89 s / 2,698 calls (execution snapshots, ~33 ms each), `simulation.py:679 _due_boundary` 68 s cumulative, `select_snapshot` 49 s, valuation `_standalone_marks` 42 s, `run_records.append` 20 s, `panel.py:214 counts` 32 s; plus two `observation_rows` panel builds at 80 s and 18 M `pytz.timezone(...)` lookups (27 s) that look like one timezone object resolved per cell.
**Resolved by:** surface (nothing to do; recorded so the numbers exist)
**Where:** `work/prof_arb-k0k5_ou-k0.prof`, summary via `work/prof_summary.py`
**What I was trying to say:** know what a session costs once my own code is out of the way.
**What happened:** roughly 0.25 s of package time per session, i.e. ~6 min for 1,349 sessions, against ~35 min lost to F-015. *After the F-015 fix* (same strategy, same run, `work/prof_arb-k0k5_ou-k0.prof`): wall 356 s vs 2,270 s before; own time 408 s = vqapr 244 s (60%), builtins/stdlib 35 s, numpy 24 s, strategy code 22 s. The package half is now: `exact_snapshot_rows` 91 s (2,698 calls, ~34 ms each — two execution-table snapshots per session, one to fill and one to mark), `observation_rows` 74 s (the two panel builds), `_due_boundary` 68 s cumulative, `select_snapshot` 48 s, `_standalone_marks` 45 s, `panel.py:214 counts` 36 s (153 M cell visits for the access record's per-name non-null counts on every read), `run_records.append` 22 s, and 27.8 M `datetime.replace` plus 18.4 M `pytz.timezone(...)` lookups (~40 s together) that look like one timezone resolution per cell inside the snapshot scan.
**What would have told me directly:** a `--profile` flag or a per-phase timing line in `vqapr run`'s result.

### F-017 — the skill says an edited component needs `vqapr register ... --force`; the CLI has no `--force`, and a plain re-register silently replaces the registration

> **Filed upstream 2026-09-03:** `qlibx/docs/issues/archive/067`. Confirmed: `_merge_component` replaces by default and its `force` parameter is a no-op; the only `--force` in the CLI belongs to `run`; the success payload never names the replaced fingerprint.

**Severity:** papercut
**Kind:** docs
**Attributable to vqapr?** Yes — the skill's "Correcting a registration during setup" section says registering a *different* declaration under a taken id "is refused" and that the ordinary loop is `vqapr register <file> --force`; `vqapr register strategy ou-k0 work/decl/ou_k0.py` with an edited file returned `ok: true` with no mention of replacement, and `--force` is `unrecognized arguments`.
**Resolved by:** surface (the plain command did what I needed)
**Where:** `vqapr register strategy ou-k0 work/decl/ou_k0.py` after editing the file (F-015 fix)
**What I was trying to say:** replace the four strategies with their fixed versions under the same ids.
**What happened:** it worked, but the surface said the opposite would happen; nothing in the success payload says "replaced a previous registration (old fingerprint …)".
**What would have told me directly:** the skill matching the CLI (either the flag exists and the plain form refuses, or the plain form replaces and says so with the old and new fingerprints).

## Where I stopped

**What the scenario asked.** Phase 1 (originally the PCA arm, amended live to FF5 + MOM, K = 6): the Table 1 row, a Figure 5 line, a reproducible run, a deviation note. Phase 2 (amended live again): K = 0 and K = 5 with OU + Thresh and Fourier + FFN, no CNN + Transformer; then, at the user's request, the strategy run profiled to find its bottleneck.

**How far it got.** Everything asked for, inside the package. Phase 1: run `ff6-ou-thresh`, SR −0.01 / μ −0.0% / σ 3.3% over 2016-12-19 → 2026-07-20 (`out/REPORT.md`). Phase 2: run `arb-k0k5`, four strategies over 2021-01-18 → 2026-07-20: OU K = 0 −0.07 / −0.9% / 12.9% (the paper's own K = 0 cell is −0.18 / −2.4% / 13.3%), OU K = 5 0.48 / 1.7% / 3.6%, Fourier + FFN K = 0 0.78 / 12.0% / 15.3%, Fourier + FFN K = 5 0.74 / 2.1% / 2.9% (`out/REPORT_k0k5.md`, `out/figure_k0k5.svg`). The FFN was written in numpy with hand-derived gradients because no ML library is installed and none can be added; it trains inside `decide()` on the declared 1,030-row window with the network in `memory`, as the surface intends. Profiling: `work/profile_run.py` runs one strategy under cProfile; the bottleneck was `PanelWindow.values` rebuilt per access (F-015, 82% of a run, 6.4x faster once bound once), and the remaining package cost is dominated by the per-read cell count for the access record on long windows (F-013, more than half of the fft-k5 run).

**What stood in the way.** Nothing blocked. Time went to: the workspace-root trap (F-004), the silent `read_strategy_table` (F-007/F-012), expressing close-on-close timing (F-010), the four-file template for a 2 × 2 grid (F-014), and the two performance traps (F-013, F-015) that a first-time user would have shipped without noticing, since the runs complete and the numbers are right either way. Memory (F-009) is the risk on the user's other machine. Not verified: determinism across two full runs; the paper's K = 5 / K = 8 cells, which the extracted `paper/` text garbles.
