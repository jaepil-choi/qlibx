# exp_236 -- where a datamodel run's memory goes, and whether processes can share a panel

Issue: `docs/issues/report-2026-09-10-a-datamodel-run-holds-memory-proportional-to-instruments-not-to-its-window.md`
(numbered `098` by the one-cube campaign). Measured 2026-09-10 on Windows 11, 32 cores.

    uv run python experiments/exp_236_the_panel_memory/gen_source.py <out.parquet>
    uv run python experiments/exp_236_the_panel_memory/measure_panel.py 309 full 2019-01-02 2026-04-30
    uv run python experiments/exp_236_the_panel_memory/measure_panel.py 309 horizon 2025-05-01 2026-04-30
    uv run python experiments/exp_236_the_panel_memory/share_across_processes.py

`gen_source.py` writes a source of the reported shape: 4,975 names, 2,955 sessions 2015-2026,
8.0M rows, 407 MB. `measure_panel.py` builds one panel through `DuckDbObservationStore` and walks
the run's sessions, reporting the process's working set and its peak; `full` builds the store with
no horizon (the registered span), `horizon` hands it the run's period (record 235). To run
it against the 0.11.0 tree, `git archive 9ce50725 src | tar -x -C <dir>` and set
`PYTHONPATH=<dir>/src`.

## The panel build (peak working set, 160-day CalendarLookback, one field)

| | 5 names | 100 names | 309 names |
|---|---|---|---|
| 0.11.0 tree, registered span (`Panel.from_rows` over dict rows) | 0.14 GB | 0.20 GB | 0.35 GB |
| develop after record 232, registered span | 0.14 GB | | 0.18 GB |
| develop, scan bounded to a 7-year run (emulated by the registered span) | | | 0.17 GB |
| develop, scan bounded to a 1-year run (emulated) | | | 0.13 GB |
| record 235, no horizon (block 7.3 MB) | 0.14 GB | | 0.19 GB |
| record 235, 7-year run horizon (block 5.0 MB) | | | 0.17 GB |
| record 235, 1-year run horizon (block 0.9 MB) | | | 0.13 GB |

The 0.11.0 slope reproduces the report (about 1 MB per name there, 0.7 here: this source's names
live for fewer sessions). The 0.32 GB the report measured is the list of 877k Python row dicts
`observation_rows` handed `Panel.from_rows`; record 232 removed it. What remains on develop is
the registered-span scan and two copies per field (Arrow name-major + numpy block). duckdb
`threads` (1 vs 32) does not move the peak.

## Four processes reading one 0.40 GB array file

| | system available memory drop | per-process RSS | per-process private | per-process time |
|---|---|---|---|---|
| `np.load` (copy) | 1.58 GB = 4 x file | +0.40 GB | +0.40 GB | 0.33 s |
| `np.load(mmap_mode="r")`, touch all | 0.48 GB = 1 x file | +0.40 GB | +0.00 GB | 0.17 s |
| memory-map, touch 309 of 4,975 names | 0.12 GB | +0.03 GB | +0.00 GB | 0.01 s |

A memory-mapped file is held once in the OS page cache for every process that maps it; RSS
counts the shared pages in every process and is the wrong number to sum. Pages nobody touches are
never read.
