# Updates since v0.1.5

> Review log of updates since v0.1.5.
> Generated 2026-06-06. Covers every commit after the `v0.1.5` tag
> (`4db8e93`). Format follows [Keep a Changelog](https://keepachangelog.com/)
> so this can later seed a `CHANGELOG.md` entry — note `CHANGELOG.md` currently
> stops at 0.1.5 and has no 0.1.6 section yet.

**Tag boundary:** `v0.1.5` = `4db8e93`, `v0.1.6` = `4a6997f`.
Exactly one commit (`4a6997f`) is *released* under the v0.1.6 tag; the
other **7 commits are unreleased features stacked on top of v0.1.6** with
no further version bump. `origin/master` currently sits at v0.1.6, so the
7 unreleased commits are the ones pending sync.

---

## 0.1.6 — 2026-05-08 (released, tag `v0.1.6`)

Single-commit patch release fixing a cloud-deploy crash.

### Fixed

- **`4a6997f` — phase0 default `start_date` to present − 4y when no slot
  specifies one.** First daily cycle on the cloud PC crashed with
  *"start_date and end_date are required when trading_dates is None"*:
  `phase0_pipeline._calculate_indicators_per_group` read `sc.start_date`
  via `getattr(..., None)`, but `SlotDeployConfig` has no `start_date`
  field, so it was always `None` → no `strategy_indicators.csv` → slot
  init failed (100% repro on fresh deploy). Now falls back to
  `present_date − 4 years` (logged at INFO); slots can still override by
  setting `start_date` on their config. Bumped `pyproject.toml` to 0.1.6.
  *(`echolon/live/orchestrator/phase0_pipeline.py`, `pyproject.toml`)*

---

## Unreleased (7 commits on top of `v0.1.6` — pending push)

Theme: **cost-model v2** for the backtest engine (qorka Wave 1A
T27/T32/T33), **multi-frequency data loading** (T23), **live-deploy
public contract** (T29/T30), and a **carry-indicator pool** (WS2). All
work is cross-repo groundwork for qorka Wave 1.

### Added

- **`dfad523` — 5-indicator carry pool + `chain_composer` (WS2, qorka
  Wave 1).** New `echolon/data/loaders/chain_composer.py` (310 lines) +
  SHFE adapter wrappers + settlement helper. Five interday carry
  indicators: `carry_front_back`, `curve_slope_near`, `risk_adj_carry`,
  `carry_z_3m`, `carry_change_20d` (all consume the `settlement` column
  from `contract_loader`). Unblocks qorka case-study-03 Stage 3 carry
  sleeve backtest. *(+1,574 lines, 14 files; new carry calculator
  package + `markets/shfe/adapter.py` + carry/chain_composer tests)*

- **`8e1215a` — T27b/c: `StructuredSlippageBroker` (per-intent +
  vol-regime cost model).** New
  `echolon/backtest/engine/structured_slippage.py`: `OrderIntent` enum
  (ENTRY/EXIT/FORCED_EXIT/OTHER), pure-function
  `classify_order_intent(...)` (position-delta semantics),
  `compute_slippage_bps(...)` (fallback chain intent→ENTRY→mean→0, plus
  strict-`>` vol-regime multiplier), and a `bt.brokers.BackBroker`
  subclass that applies per-order slippage at fill time. Replaces the
  transitional *mean-of-intents* degrade fallback in
  `backtrader_engine.py`; log went WARN→INFO ("Per-order intent
  classification active"). Provider failure is swallowed (can't crash a
  backtest). 24 new tests; full backtest suite green (79 tests).

- **`e681614` — T23: multi-frequency `load_ohlcv` (qorka Q48 NEGATIVE
  finding).** Backward-compatible new keyword-only param
  `frequency: Literal["1d","1m","5m","15m","1h"] = "1d"`. Default `"1d"`
  preserves the legacy `{dir}/{MARKET}/{asset}/sort_by_date.csv` layout;
  intraday resolves to a frequency-disambiguated subdir
  `{dir}/{MARKET}/{asset}/{frequency}/sort_by_date.csv`. Date filter
  auto-detects `date` (daily) vs `datetime` (intraday) column. 16 new
  tests; data suite 61/61. *Known UX gap (Wave 2):* `end_date` parses to
  midnight, so intraday callers pass next-day to include a full day.

- **`4f30020` — T29 `pathway_id` field + T30 `workspace/deploy/slots/`
  public contract.** T29: `pathway_id: Optional[str] = None` on
  `TradingDataRecord` (`echolon/live/io/data_logger.py`) — per-pathway
  identifier for paradigms that decompose signals into named pathways
  (TRS P1..P8); consumed by qorka's A9 live-replay diagnostic for
  per-pathway hit-rate drift. T30: the `workspace/deploy/slots/` path
  layout is now a **documented semver-stable public contract** in
  `echolon/live/__init__.py` (`DEPLOY_SLOTS_DIR_TEMPLATE`,
  `DEPLOY_PORTFOLIO_DIR`, `SLOT_STATE_FILE`, `SLOT_TRADING_DATA_PATTERN`,
  `SLOT_TRADE_EXECUTIONS_PATTERN`, `PORTFOLIO_DASHBOARD_FILE`). Renames
  inside this tree are now semver-breaking. 4 new tests; live suite (178)
  green.

- **`66fd570` — ContractSpec cost-model v2 fields + 3-tier precedence.**
  Adds `calibrated_slippage_bps_by_intent` (Optional[dict],
  ENTRY/EXIT/FORCED_EXIT), `high_vol_slippage_multiplier` (=1.0),
  `high_vol_pct_threshold` (=75.0), and `tail_factor` (=1.0, Wave-2 stub)
  to `ContractSpec`. Engine precedence: (1) v2 by-intent → custom broker
  (preferred), (2) v1 scalar → `set_slippage_perc`, (3) tick-derived
  default. Shipped the v2 *contract*; the consuming broker landed in
  `8e1215a`. 11 new tests.

- **`59bfd4c` — `ContractSpec.calibrated_slippage_bps` live-calibrated
  override (v1 scalar, qorka Q47 Option A).** Per-contract slippage
  override; `backtrader_engine` prefers it over the tick-size-derived
  default when set. Background: qorka A9 showed 3 deployed TRS strategies
  diverging from backtest because the tick-derived default systematically
  under-estimated slippage for SHFE non-ferrous futures. Populated by
  qorka's A9 cost-calibration workflow at config-injection time. 7 new
  tests.

### Fixed

- **`04e6dd0` — T23 audit fix: use `raise_error("DAT-005")` per
  error-catalog policy.** Caught in qorka session-1 ratification audit:
  `e681614` used a bare `raise ValueError(...)` for unsupported
  frequency, violating echolon's catalog-only error policy
  (`tests/test_error_catalog_compliance.py`). Added `DAT-005`
  ("Unsupported OHLCV frequency parameter") to `errors.py` with
  fix_template + context spec, added `codes/DAT-005.md` docs page and
  README index entry, switched the raise, and updated the T23 test to
  assert `DataError` / `DAT-005`. Net: 970/970 echolon tests pass.

---

## Sync summary

| | |
|---|---|
| Commits since v0.1.5 | 8 |
| Already on `origin/master` (v0.1.6) | 1 (`4a6997f`) |
| **Pending push** | **7** (`59bfd4c` … `dfad523`) |
| Current version | 0.1.6 (no bump for the 7 unreleased commits) |
| `CHANGELOG.md` touched | No (separate temp doc, as requested) |
