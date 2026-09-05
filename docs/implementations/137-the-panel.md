# 137 — the Panel: grain is declared, lookbacks follow it, a table sits between the file and the window

**Closes:** `docs/issues/035`. **Step:** 5 of
`docs/refactoring/2026-09-02-the-convergence-campaign.md` (M5).
**Authority:** `docs/design/the-panel-the-surface-and-the-run.md` §2 (the contract), §7-1 and §7-3
(RESOLVED), §7-2 and §7-5 (their stated candidates); the owner's ruling of 2026-09-02 on the read
verb (option B, design §2.5 as written); architecture §17.1.1–17.1.4, §17.9, §17.10.

## Why this exists

The data plane had two layers, the declaration and the window, and no table between them: every
read re-cut its window on the parquet with SQL. `049` measured what that costs — the same model,
the same output, 806.61 s against 1.31 s, `compute` at 0.36 s on both sides. Ninety-eight percent
of a rolling-window run was moving data. And the lookback a cross-sectional model reached for
counted per name (`033`: 1,637 names, `rows=313`, a batch spanning 1,865 sessions), which the
package could not steer it away from because nothing in the type system knew what a table *was*.

The design's answer is one noun with three consequences: a dataset declares its **grain**; the
**lookback types follow the grain**; and a panel grain is read as a **Panel**, built once per run
and sliced per read. The design's own warning is that the second consequence changes what an
existing word means, silently on a balanced panel, and that only the first consequence — every
registration edited once by hand — can break the silence. So the four slices ship in one merge.

## Rulings

| question | ruling |
|---|---|
| `grain` | declared on every registration — `instrument_instant`, `instant`, `rows` — never derived; absent or unknown is refused naming the three values **and** what `RowsLookback` now means. |
| a workspace written before `grain` | opens; its grain-less entries list, remove and re-register; every read on them is refused with the same message. Never silently `rows` (§7-3). Registering again with a grain is the repair, not a conflict. |
| uniqueness axis (§17.1.2) | the grain's: `(available_at, instrument)`, `(available_at,)`, or the author's `key_fields` for `rows`. A grouped projection on a panel grain is unique by construction and is not scanned. |
| `RowsLookback(n)` | on a panel grain, the table's last n rows — the same instants for every name — bounded by arithmetic on the source's instant grid. |
| `InstantsLookback(n)` | each name's own last n reported instants, per field: what `RowsLookback` meant; `grain: rows` only. |
| steering | a panel lookback on a rows grain, and an instants lookback on a panel grain, are refused by name at preflight and at the read, from one rule beside `Grain`. |
| the read verb | **owner ruling B**: `read(alias, field)` returns the 2d window on a panel grain; `rows(alias)` streams `Observation`s on `grain: rows`; each refuses the other grain. One verb per shape; the shape follows the declaration. |
| the panel's life | in-process, on the run's store, keyed by content identity (source digest, dataset, fields, instruments, span). Spill across processes and a `prepare` verb: with Noun 3 (§7-2, §7-5). |

## What changed

### M5.1 — grain

`DatasetRegistration.grain`; `of(...)` requires it and checks it against the instrument axis;
`check_key` proves the grain's axis; the codec writes it and decodes its absence as *undeclared*;
the declaration reader refuses a missing or unknown grain with its own code
(`declaration.read.grain_undeclared`); reads refuse an undeclared grain
(`dataset.register.grain.undeclared`); published datasets state `instrument_instant`, which the
publication authority guarantees; `show dataset` reports it; the dataset template declares it
with the three values explained. Every registration in this repo's tests, showcases and shipped
sample carries a grain now — a one-time migration decided per site by its keys, then corrected by
hand where the keys lied (long tables whose expressions collapse to one row per pair are
`instrument_instant`; the vendor-grain proofs are `rows`).

### M5.2 — lookbacks follow the grain

`InstantsLookback`; `PanelLookback` / `SeriesLookback`; `RowsLookback` on a panel grain bounds by
the instant grid (`store._grid_bound`); `InstantsLookback` keeps the per-name ranking the read
always had; `lookback_fits_grain` beside `Grain`, applied at preflight and at the read; the
scaffold gains an `instants` flavour and the CLI `--instants-lookback`; `authoring`, `public`, the
lineage and the workspace codec carry the new type. Measured: `RowsLookback(2)` on a sparse
panel spans two instants and the stopped name contributes nothing; `InstantsLookback(2)` on the
same table as `rows` reaches that name's own last two.

### M5.3 — the Panel

`data/panel.py`: `Panel` (fields x instruments over one instant axis, Arrow columns, content
identity) built by `from_rows` from the rows one scan returned; `PanelWindow` (two indices;
`instants`, `instruments`, `values[name]`, `latest()`, `series()`, per-name counts for the access
record). `store.panel_window` builds or finds the panel and slices it; `ModelWindow.panel`
records the access; the three contexts implement `read(alias, field)` and `rows(alias)` with the
grain deciding; the three authoring contracts declare both. Measured: two fields, three cutoffs,
two consumers — **one scan**; the window's Arrow slice shares the panel's buffer; the byte-identical
regression (`tests/acceptance/test_the_panel_and_the_rows_agree.py`) — the same arithmetic on a
panel registration and a rows registration, bidirectional anti-join **zero rows**.

### M5.4 — migration and the claim

The shipped cap reads its benchmark as `read(alias, field).latest()`; the sample and the three
scaffolds read a window; `SKILL.md` recommends `grain: instrument_instant` for a date x ticker
table (architecture §17.1.1 was *부분* because it recommended the other way) and describes the
two verbs; four showcases and the tests that read moved. `035` CLOSED; §17.1.1–17.1.4, §17.9 and
§17.10 carry dated corrections; the design's §2 is marked implemented and §7-2/§7-5 note the
candidate taken.

## Trade-offs

**The largest breaking change of the campaign, by design.** Every registration edited once; every
`read(alias)` consumer moved to `read(alias, field)` or `rows(alias)`. Testbed projects'
declarations and models are theirs to edit, and the refusal tells them what to write.

**`CalendarLookback` is refused on `grain: rows`.** The design's typing rule puts it under
`PanelLookback`; a calendar window on a long table is a coherent question the rule does not
admit. Stated rather than softened; if it bites, it is one line in `lookback_fits_grain`.

**A panel is built from scan rows in Python.** One `observation_rows` call per alias per run,
then a per-cell pivot into Arrow arrays; the window is then arithmetic. The scan path is reused
unchanged, so grouped projections, expression fields and the PIT predicate hold by construction.
The pivot's cost is paid once; the design's per-window number (10.19 s → 0.048 s) is the shape of
what every read after pays.

**No measured baseline against 806.61 s.** The harness is gone (record `136`). What this record
measures is structural: scans per alias per run (one), and the byte-identical regression.

**The refusal-code baseline was regenerated** for the two grain codes.

## Validation

```
uv run ruff check src/                           All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs         1304 passed, 14 deselected
PYTHONUTF8=1 uv run pytest tests/ -q -m slow -rs  14 passed
```

Branch parent `develop @ 8d403b50` (record `136` merged), measured: **1274 passed / 14
deselected** fast; **14** slow; showcases 9 of 9.

**Showcases: 9 of 9.** Every showcase completes on this tree, including the four whose models
moved to `read(alias, field)`.
