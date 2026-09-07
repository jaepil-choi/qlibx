# 163 — the report is read from the record: one API, no renderer

**Closes:** no issue; files `docs/issues/087` on the way (one parquet part per occurrence,
ruled: compaction on `release()`, its own branch). **Branch:** `reporting-api`, off
`develop @ 6717c469` (rebased onto the 0.5.0 stamp, after record `162`). **Campaign:** none. **Authority:** the owner,
2026-09-07 — a Python API only, no CLI verb; visualisation belongs to the skill; the three
metric conventions below. **Design:** `docs/design/report-from-the-record.md`.

## Why this exists

Two 0.4.1 workspaces measured their runs before any API existed and each re-derived the same
things by hand from the four recorded tables: NAV statistics, a benchmark-relative row, costs
summed from `vqapr.fill`, breach counts from `vqapr.monitoring`, a cumulative-return figure
(`kaist-thesis/vqapr-scenario-testbed/work/analyze.py`,
`kwam-enhanced-index/vqapr-enhanced-index-3/measure_ensemble.py`). `vqapr.analysis` had the
pure statistics (`returns`, `drawdown`, `fill_summary`) and no path from a record on disk to
them, so nobody used them. PRD UC-REPORT-001 already fixed the boundary: values and a
machine-readable renderer from the package, charts from the user over the same values.

## What changed

- **`src/vqapr/report/`**, new. `document.py`: `StrategyReport` (sections `performance`,
  `book`, `attribution`, `trading`, `intent`, `compliance`; `omitted` names every section the
  record cannot give and why) and `RunReport` (`headline`, `correlation`, `relative`), pydantic,
  frozen, `as_record()` → JSON with `Decimal` as text and zoned instants. `measure.py`: rows →
  sections, pure functions of the four tables; reuses `analysis.performance.returns`/`drawdown`
  and `analysis.execution.fill_summary`. `record.py`: the door, through `vqapr.flow.record`.
- **`vqapr.public`** exports `strategy_report`, `run_report`, `StrategyReport`, `RunReport`.
- **`flow/record.py`**: `_resolve_ref` is `resolve_strategy_ref` — public, unchanged, so the
  report resolves `<id>` / `<id>@<fp8>` / `None` exactly as `read_table` does.
- **`SKILL.md`**, Rung 3: what the report holds, how to render a paper's tables and figures
  from it in the project's own plotting library, and a house style for the figure.
- **`docs/issues/087`** filed and indexed; `docs/design/report-from-the-record.md` written.

## Conventions (the owner's three, and the ones they implied)

- Sharpe against `risk_free_annual`, zero by default; the record holds no rate.
- Three hit rates, three names: `positive_period_share`, `position_hit_rate`,
  `weight_sign_hit_rate`.
- A name's side for a period is its opening side; a flip inside a period goes to the opener.
- The grid is the valuation instant; a fill belongs to the period whose closing
  `account_version` is the first at or above its own. When the first valuation already reflects
  a fill and the initial positions were empty, the initial cash stands as the first point.
- Realised turnover is one-way (`Σ|dealt×price| / 2 / NAV`), like the intended one, so the two
  compare; their gap is the size of what did not execute.
- `residual` (ΔNAV − Σ per-name P&L) is a reported series, never absorbed.
- `periods_per_year` is inferred from the grid's median spacing and declared `inferred`.
- A monitoring row without `verdict` (before record `158`) follows the author's `passed` and the
  constraint is marked `tolerance_judged: false`.

## Validation

- `tests/report/test_the_report_reads_the_record_back.py` (13): a hand-computed record — initial
  1000, long A / short B, three valuations, four fills and a refusal, two decisions, two
  constraints. Per-name P&L sums to ΔNAV to the digit and splits by side; turnover, costs, the
  refusal, intent gap, sign hits, compliance buckets, a positions-less record's `omitted`, a
  cash-only book's residual, the run report's headline / correlation / relative, JSON round
  trip, refusals by name, `periods_per_year` inference.
- `tests/report/test_a_real_run_reports_and_adds_up.py` (slow): the shipped sample journey,
  reported; residual zero everywhere, P&L equals the NAV change, the first valuation is the
  initial book.
- **Against the workspaces' own numbers** (`measure_ensemble.json`, run `ensemble-k200`):
  annualised return / volatility / Sharpe / max drawdown for the three books, cost in basis
  points (13.11 / 12.09 / 10.99), `fund-concentration` 835 held / 833 breached with worst excess
  4.89%p and A005930 as top offender — identical. `ff-arm` (kaist): `ou_k0` Sharpe 0.348 and
  volatility 17.05% against the testbed's 0.35 / 17.1 on its own headline series.
- Fast suite on the branch, rebased onto Step 7: **1,413 passed, 4 skipped** (486 s). `tests/boundaries/test_public.py` updated for the four
  exports.

## Cost noted

`run_report` on `ff-arm` (8 strategies, 607 sessions, 19,452 parquet parts) takes ~130 s, most
of it opening parts; `087` is the fix, not this module.
