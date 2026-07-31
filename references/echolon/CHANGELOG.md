# Changelog

All notable changes to echolon are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/). Pre-1.0 minor and patch
versions may carry breaking changes — they are clearly flagged below.

## [Unreleased]

## 0.3.0 — 2026-07-27

### Removed — BREAKING

- Removed `PortfolioDeployConfig.output_bank_dir`, which defaulted to
  `"../output_bank"`. A workspace-wide scan found no reader of the attribute in
  any repo, so the field was deleted rather than re-pointed: a default naming
  someone else's artifact store is wrong at every value, including a renamed
  one. Host applications that keep an `output_bank_dir` key in their deploy JSON
  already parse it themselves; `PortfolioDeployConfig.load()` still accepts such
  files and simply does not absorb the key.

### Changed — BREAKING

- `scripts/build_gfex_expiry_data.py --bars-root` and
  `scripts/build_czce_new_products_expiry_data.py --panel-contracts-root` are now
  **required**. Both previously defaulted to a store path derived from the
  location of the checkout; omitting them is now an argparse error rather than a
  silent read of a guessed directory.

### Fixed

- The artifact-backed market and panel falsifiers resolved their store as
  `Path(__file__).resolve().parents[4] / "output_bank/..."` — one directory above
  the real store. Because a missing artifact caused `pytest.skip`, nine
  falsifiers reported `skipped` against a path that could never exist, and a skip
  is indistinguishable from a pass in a suite total. They now take an injected
  path and, with the store supplied, all nine run and pass.

### New

- Store locations are injected, never derived. `tests/conftest.py` resolves each
  artifact from `DOLPHINQUANT_STORE_ROOT` (or an artifact-specific variable) and
  is deliberately three-valued: nothing injected skips, an injected-but-absent
  path **fails loudly** naming the variable that supplied it, and a correct
  injection returns the path. `DOLPHINQUANT_P2_V5_CONTRACTS` is new; the other
  artifact variables keep their existing names.
- `tests/config/test_store_path_injection.py` pins the seam: no field of
  `PortfolioDeployConfig` defaults to a store path, the build scripts refuse to
  run without an explicit root, and no store name survives in their source. Each
  guard ships with both a seeded failure and a passing control.

### Notes

- echolon no longer contains a store location of any kind, so the artifact store
  can be renamed or relocated without editing this repo. Callers must supply the
  path; nothing here falls back to a default.

## 0.2.0 — 2026-07-07

### New

- Added `echolon.panel` immutable multi-instrument panel loading, manifest hash
  verification, no-lookahead `PanelView`, curve access, metadata access, and QC
  reports.
- Added `echolon.signals` public `SignalEngine` / `ScoreVector` contract plus
  validation for score caps, explicit `None` missing-data scores, deterministic
  compute, and identity-literal rejection.
- Added `echolon.portfolio` book-state models, score combiner, volatility
  constructor, sector and margin caps, book-risk snapshots, and pure
  `PortfolioStrategy` composition.
- Added `echolon.backtest.book` purpose-built daily futures book backtester with
  one cash account, next-session fills, slippage/commission costs, futures
  margin, forced-liquidation events, and deterministic artifacts.
- Added `echolon.bundle` manifest schema, total file-hash coverage, hash
  verification loader, and `echolon-bundle verify`.

### Changed

- Panel QC now keeps structural data defects blocking while treating
  settlement/close divergence and daily-return outliers as review warnings for
  broad futures panels.

### Deferred

- `native/`, `mcp`, and `backtest/portfolio_runner.py` archival is deferred:
  qorka still imports `echolon.backtest.portfolio_runner`, and qorka agent
  tooling still references `echolon.native` / `echolon.mcp`.

### New

- `WFARunner` accepts a generic `binding_resolver_fn` (mirrors the existing
  `selection_score_fn` pass-through): an opaque per-window callable whose
  returned mapping is overlaid onto the window's search-space function and
  default params via a new schema-agnostic recursive key-overlay. Default
  `None` is byte-identical. `BaseComponent.get_market_regime` gains an
  optional `column` override (default `None` = unchanged) so a host app can
  point one call at a differently-named regime column per window.
- `catalog.validate` now accepts derived-column names matching two grammars:
  (a) `{base}__fit{YYYYMMDD}` where `base` is a known regime column
  (`market_regime`, `session_phase`, `session_phase_agg`) or a registered
  classifier — vintage-suffixed regime columns bypass IND-004; (b)
  `{base}_pctl_{N}` and `{base}_z_{N}` where `base` is a catalog indicator
  — windowed percentile/z-score derived columns bypass IND-004. Grammar
  documented as module-level regex pair in `echolon/indicators/catalog.py`.
- `EnrichedPandasData.from_metadata` now hard-fails at construction with an
  actionable `ValueError` when any `indicator_columns` entry is not a valid
  Python identifier (e.g. names with dashes or spaces). Previously such
  columns would silently fail at first backtrader attribute access.

- ``OptimizationMetrics.daily_returns: Optional[Dict[str, float]]`` — per-trial
  daily returns carried from the backtest engine's ``timereturn`` analyzer through
  the full pipeline: ``_extract_metrics`` → ``OptimizationMetrics`` → IPC dict
  (ProcessPool-safe via standard pickle) → ``OptunaOptimizer._per_trial_returns``.
  ``save_study_results`` writes ``per_trial_returns.json`` alongside the existing
  ``optimization_trials.csv``; shape ``{trial_number: {date: return}}``, successful
  trials only. Failed (``TrialState.FAIL``) trials are excluded entirely; the
  ``skipped_trials`` list names COMPLETED trials whose returns data was absent,
  so their omission is honest rather than silent.
  Size note: 50 trials × ~4k days ≈ few MB (FLAG-2).

- ``TrialSelector`` gains optional ``selection_score_fn: Callable[[pd.Series,
  Mapping[str, Any]], float]`` and ``per_trial_returns: Optional[Mapping]``.
  Default ``None`` → byte-identical built-in ``risk_adjusted_return.idxmax()``
  ranking (pinned by test). When provided, the callable's score replaces the
  built-in ranking within the winning cluster only; clustering and drawdown
  threshold are unchanged. The second argument to the callable is
  ``per_trial_returns`` (or ``{}``) so callers can implement OOS scoring
  without coupling the mechanism to any specific policy (FLAG-1).

- ``WFARunner.__init__`` gains optional ``selection_score_fn: Callable[[pd.Series,
  Mapping[str, Any]], float]``, forwarded verbatim to every per-window
  ``TrialSelector`` it constructs (FLAG-1 pass-through for the WFA path).
  Default ``None`` reproduces the built-in ranking byte-for-byte (pinned by
  test). Each window's ``TrialSelector`` also receives that window's
  ``OptunaOptimizer._per_trial_returns`` as ``per_trial_returns`` — the
  optimizer instance is still in scope in-process when the selector is
  built (no reload of the ``per_trial_returns.json``
  ``save_study_results`` already wrote), so this is a genuine in-memory
  forward, not a re-read from disk. Task ED.

- ``echolon.indicators.run.compute_indicators_from_frame(ohlcv, indicator_list,
  ctx, *, regime_params=None) -> pd.DataFrame`` — a generic injectable-frame
  indicator entry point for callers that already hold a continuous OHLCV
  ``DataFrame`` in memory (block-bootstrap resamples, synthetic data, ...) and
  want the same per-bar computations ``run_indicator_calculation`` applies to
  its stitched main-contract series, without touching contract files or the
  roll table. Runs the existing per-contract compute path
  (``_compute_indicators_for_contract``) directly over the caller's frame in a
  single pass — genuine "post-stitch continuous-series" semantics. Identity
  holds exactly (modulo TA-Lib's incremental-sum float non-associativity,
  ~1e-9) for any bar whose lookback window doesn't cross a main-contract
  change in the caller's series; bars within ``lookback - 1`` of a change
  diverge from the standard pipeline because that pipeline used the
  incoming contract's own pre-roll price history, which a bare continuous
  frame does not carry — documented on the function, and proven (not just
  asserted) by the new identity test in
  ``tests/indicators/test_compute_from_frame.py``, which shows both the
  match zone and the divergence zone from one real (non-mocked) two-contract
  roll fixture. ``curve_carry``-kind indicators (built from the full
  multi-contract forward curve, e.g. ``carry_front_back``) cannot be
  reproduced from a single frame at all and now hard-fail with the new
  **IND-009** error rather than being silently dropped or approximated.
  Registered regime classifiers are included for free (same dispatch path)
  but are out of scope for "held constant across resamples" — that's the
  caller's job. On an intraday ctx, a caller-passed ``regime_params`` is
  forced to ``None`` — mirroring ``IndicatorProcessor.__init__``'s routing
  (regime params kept only for interday frequency; intraday uses
  session_phase + volatility_state) — so the frame path never computes
  something the standard pipeline wouldn't; pinned by test with a spy
  classifier. The shared pre-compute normalization (missing OHLC fill,
  date conversion, sort) used by both the per-contract path and this new
  entry point is now a single-sourced helper, ``_prepare_ohlcv_frame``, in
  ``echolon/indicators/engine/processor.py`` (previously inlined only in
  ``process_single_contract``). Discoverable via the new
  ``compute_indicators_from_frame`` skill
  (``echolon/native/skills/echolon_api/compute_indicators_from_frame/SKILL.md``,
  indexed in ``SKILLS.md``), which documents the roll-boundary divergence,
  the IND-009 curve_carry exclusion, and the regime-params caveats
  prominently for MCP discoverers.

### Fixed

- `__version__` in `echolon/__init__.py` updated from `0.1.3` to `0.1.9`
  to match `pyproject.toml`.

## 0.1.5 — 2026-05-08

Live-deploy hardening release. The ``PortfolioTradingRunner`` god-class
in ``echolon.live.orchestrator.portfolio`` is decomposed into focused
collaborators with behavioral equivalence preserved verbatim. Slippage
caps and circuit-breaker thresholds in ``order_policy`` are tightened
to align with realistic SHFE strategy edge. ~85 new tests added across
the live module surface. Phase 0 fail-loud-on-xtdc-unavailable closes
a class of stale-data trading risk.

### Breaking changes

- ``echolon.live.config.order_policy.MAX_SLIPPAGE_PCT_BY_CLASS`` values
  tightened by 3-10×. Previous defaults exceeded typical SHFE
  non-ferrous per-trade strategy edge by an order of magnitude. New
  values: ``ENTRY=0.0020`` (was 0.02), ``EXIT=0.0080`` (was 0.05),
  ``FORCED_EXIT=0.0150`` (was 0.05). Hosts that previously relied on
  the looser defaults to keep marginal fills should override these
  constants explicitly via subclassing or monkeypatch.
- ``echolon.live.config.order_policy.CIRCUIT_THRESHOLDS`` tightened:
  ``abandoned_rate_pct=0.20`` (was 0.4), ``rejected_rate_pct=0.25``
  (was 0.5), ``abandoned_rate_min_n=10`` (was 5).
- ``PortfolioTradingRunner._phase0_data_pipeline`` now raises
  ``RuntimeError`` when ``XtdcClient.connect()`` fails, instead of
  logging error and silently skipping the cycle. Hosts that depended
  on the silent-skip behavior must catch the exception or repair their
  data pipeline.
- ``echolon.live.config.order_policy.TICK_SNAPSHOT_MAX_AGE_S`` raised
  ``2.0 → 4.0`` to accommodate SHFE off-peak tick gaps. Hosts on other
  exchanges should override.

### New

- ``echolon.live.orchestrator.phase0_pipeline.Phase0DataPipeline`` —
  extracted from ``PortfolioTradingRunner._phase0_data_pipeline``. Now
  independently testable. Constructor takes ``(config, log)`` and
  ``.run(present_date)`` executes xtdc connect → per-instrument data
  download → per-group indicator calculation.
- ``echolon.live.orchestrator.scheduler.DailyScheduler`` — extracted
  APScheduler instance + 7 calendar-aware scheduling methods
  (``_schedule_daily_trading``, ``_market_open_job`` callback,
  ``_reschedule_next_job``, ``_get_schedule_time``,
  ``_find_next_trading_day``, ``_ensure_trading_calendars``,
  ``_write_scheduler_heartbeat``). Constructed by the runner with
  callback hooks; runner's ``_market_open_job_inner`` stays in place.
- ``echolon.live.orchestrator.portfolio.book_terminal_record`` —
  module-level helper deduplicating the FILLED / CANCELED / REJECTED
  bookkeeping branches in ``_process_fills``. Hardened: refuses to book
  FILLED records with ``intent=None`` (was a phantom-fill silent path);
  ``order.status`` mutation is now atomic with VP update inside the
  inner try/except (was set before the try, leaving state inconsistent
  on VP failure); REJECTED / CANCELED branches now have inner
  exception handling with branch-distinct log messages.
- ``echolon.live.slot.trading_slot.TradingSlot`` gains four methods
  moved off the runner: ``set_pending_exit_intent``,
  ``clear_pending_exit_intent``, ``update_pending_exit_remaining``,
  and ``build_snapshot_data``. Pending-exit StateManager mutations are
  now slot-owned; runner-side wrappers preserved for log-namespace
  equivalence.
- ``echolon.live.slot.risk_overlay.PortfolioRiskOverlay.peak_equity`` —
  public property replacing ``hasattr`` reach-in to
  ``_peak_portfolio_equity``.
- ``Phase0DataPipeline`` ``log.critical`` + ``RuntimeError`` on xtdc
  unavailability with explicit message text for ops triage.
- ``DailyScheduler._get_schedule_time`` logs a warning before falling
  back to night-market schedule on calendar-failure (was silent).
- ``echolon.data.live_data.run_live_data_update`` now copies
  ``main_contract.csv`` from ``<symbol>_by_contract/`` to the
  canonical loader path as a final pipeline step. Previously the
  runner crashed at slot.initialize with ``DAT-003`` on first cycle.

### Fixed

- Calendar API mismatch: ``is_trading_day`` /
  ``is_night_market_open`` / ``get_trading_dates`` /
  ``get_main_contract`` are kw-only in ``market_data_dir``; six call
  sites in the runner + slot were missing the kwarg, raising
  ``TypeError`` at startup.
- ``portfolio.py`` was passing positional args where new
  ``run_indicator_calculation(paths=...)`` is required.
- ``_apply_fill_to_vp`` is removed (inlined into the new
  ``book_terminal_record`` helper); dead ``_map_intent`` static method
  removed (post-OrderRouter migration); dead ``xtconstant`` import
  removed.
- ``PortfolioRiskOverlay.peak_equity`` access via property no longer
  collapses 0.0 peak to ``portfolio_equity`` (the original ``hasattr``
  guard returned 0.0 verbatim; the property preserves that exactly).

### Removed

- ``PortfolioTradingRunner._map_intent`` (dead since OrderRouter
  migration; no callers).
- ``PortfolioTradingRunner._apply_fill_to_vp`` (inlined into
  ``book_terminal_record``).

### Internal

- ``portfolio.py`` shrunk from 1740 → 1308 LOC (-25%) without losing
  any user-visible behavior.
- New test files: ``test_phase0_pipeline.py``, ``test_daily_scheduler.py``,
  ``test_book_terminal_record.py``, ``test_trading_slot_pending_exit.py``,
  ``test_trading_slot_snapshot.py``, ``test_capital_slot.py``,
  ``test_portfolio_risk_overlay.py``, ``test_cross_slot_isolation.py``,
  ``test_scheduler_time_selection.py``, ``test_data_logger_contract.py``,
  ``test_shfe_bands_bounds.py``, ``test_state_manager_invariants.py``,
  ``test_order_policy_bounds.py``. Test count rose 695 → 778.
- New bounds-test pattern: ``test_order_policy_bounds.py`` and friends
  assert *upper* bounds on safety constants rather than exact values,
  catching accidental relaxation in future commits.

## 0.1.3 — 2026-05-05

User-facing logging cleanup. ``echolon hello`` and the default
``echolon backtest single`` path no longer flood stdout with per-bar
``[DEBUG] Bar N | START/END`` and ``[DEBUG] Risk | TRADING_ALLOWED``
trace lines. Pass ``--verbose`` (or ``-v``) to restore that trace.

### New

- New ``summary`` run_context (``echolon.backtest.logging_utils``).
  Root INFO so workflow milestones remain visible
  (``[BACKTEST_RUNNER] Complete``, ``[STRATEGY_BRIDGE] Indicators``);
  bar-loop loggers (``backtrader_strategy``, ``strategy.component``,
  contract-aware/session-aware hooks) demoted to WARNING so per-bar
  trace is suppressed. ``echolon hello`` and non-verbose
  ``echolon backtest single`` now use this context by default.

### Fixed

- ``should_log_details`` now correctly gates only ``debug`` and
  ``best_trial`` (was: every non-``optimization`` context). The new
  ``summary`` context returns False, matching user expectation that
  the default invocation prints a one-line Sharpe summary, not 1500
  lines of per-bar trace.
- ``BacktestRunner.run`` no longer silently coerces unknown contexts to
  ``best_trial``. Canonical contexts (``optimization``/``summary``/
  ``debug``/``best_trial``) pass through verbatim; non-canonical
  legacy values (``custom``/``manual``/``backtest``) still fall back to
  ``best_trial`` for back-compat.
- ``echolon.backtest.logging_utils._current_context`` ContextVar default
  changed from ``"debug"`` to ``"summary"``. Test paths and library
  callers that hit the logger without first calling
  ``setup_backtest_logging`` no longer flood stdout.
- ``echolon backtest single --verbose`` help text corrected — previously
  claimed it surfaced a DEBUG-level trace, but the trace was always on
  regardless of the flag. Now the flag actually controls the trace.

## 0.1.2 — 2026-05-04

Second public release. Hardens the dependency-injection contract, trims the
CLI surface, fixes a backlog of path-resolution bugs surfaced by host-app
integration, and ships `llms.txt` directly into scaffolded workspaces.

### Breaking changes

- **`PathsConfig` is now required everywhere.** Every library entry point
  (`run_data_pipeline`, `run_backtest`, `run_best_trial`,
  `run_indicator_calculation`, `WFARunner`, `PortfolioBacktestRunner`, …)
  takes `paths: PathsConfig` as a kwarg-only required parameter. Library
  code no longer falls back to `PathsConfig.from_env()`; the strategy
  bridge raises `CFG-003` if path strategy params aren't injected.
  Construct one `PathsConfig` at startup (via
  `PathsConfig.from_project_root(<root>)` or `from_platformdirs`) and
  thread it through.
- **`echolon run` removed.** Use `echolon backtest single <strategy_dir>` —
  it walks up to the workspace marker and recovers ctx, so no flags are
  required.
- **`echolon init-strategy` back-compat alias removed.** Use `echolon init`.
- **Default workspace layout flattened**: `workspace/strategy/baseline/` +
  `workspace/backtest/` (was `workspace/current/...`). Host apps with
  iteration-loop layouts override via the workspace marker's `paths` field.
- **Legacy strategy imports**: `from ...core.base.X` no longer resolves.
  Run `echolon migrate <strategy_dir>` to rewrite to the current absolute
  paths (`echolon.strategy.X`).
- **`Position` field cleanup**: `entry_price`, `side`, `is_short`,
  `is_flat` removed; only `is_long` survives. Use `position.avg_price`
  for the entry price; check direction via `position.direction`
  (`"LONG"` / `"SHORT"` / `"FLAT"`).
- **Pydantic v2 idioms**: strategy output schemas use
  `model_config = ConfigDict(extra="allow")` instead of the deprecated
  `class Config:` block.

### New

- **`llms.txt` shipped into every workspace.** `echolon init` /
  `echolon hello` drop the agent orientation manual at the workspace
  root, so an LLM agent walking into the project finds it without
  needing the MCP server up.
- **Data pipeline auto-populates `main_contract.csv`.** Step 6 of
  `run_data_pipeline` either copies a curated `main_contract.csv` from
  the raw data tree or derives it via the max-volume rule. Previously a
  separate scaffolding step.

### Fixed

- WFA OOS replay: paths threaded through `BacktestRunner.best_trial`,
  `get_trading_calendar_instance`, `load_indicator_metadata`, and the
  SHFE adapter's `market_data_dir`. Resolves a chain of `CFG-003`
  errors that fired on every per-window backtest.
- Contract-aware broker now probes slot-style indicator dir first and
  falls back to instrument-style
  (`{indicator_dir}/{slot}/by_contract/` or
  `{indicator_dir}/{instrument}/by_contract/`) — supports both
  `echolon backtest single` (slot layout) and host-app iteration-loop
  pipelines (instrument layout).
- SHFE day-data extractor default subdir aligned with the natural
  convention: `{raw_data_dir}/SHFE/day_data/` (was the misleading
  `raw_data/`).
- README runtime-registration table: corrected OpenAI Agents SDK row
  (previous form raised `TypeError`; now uses the required `params`
  dict), added the missing outer-wrapper note for Cursor's `mcpServers`
  config, replaced the vague Codex CLI pointer with the documented
  `codex mcp add` command, replaced the LangChain pointer with a
  copy-pasteable `MultiServerMCPClient` snippet.

### Internal cleanup

- Removed `validation-backup/` skill tree from echolon (relocated to
  qorka — the KEEP/REVERT workflow is qorka-internal, not generic
  backtest infra).
- Renamed test fixture `al_v6_1_migrated/` → `aluminum_baseline/` and
  scrubbed qorka-specific path references from fixture file headers.
- Skill-doc audit pass: removed qorka-internal class names
  (`ExplorationOrchestrator` / `ExploitationOrchestrator`),
  internal-task-tracker references ("Task 6 audit"), and outdated
  migration framing.
- README rewrite (EN + zh-CN): trimmed from ~265 lines to ~104,
  restructured around the two journeys readers actually have (try via
  CLI in 30 seconds; drive from an LLM agent). Native-Chinese tone
  pass to drop translation-shaped phrasings.

## 0.1.1 — 2026-04-18

First public release on PyPI. SHFE daily futures research toolkit for LLM
agents — bundles an MCP server, in-package skills, catalogued error codes,
typed Pydantic configs, working strategy templates, Backtrader-based
backtesting, Optuna TPE optimization (single + multi-objective),
walk-forward analysis with deployment-readiness scoring, and KMeans-based
robust trial selection. Production engine inside
[Qorka](https://dolphinquant.com), DolphinQuant's AI-native strategy
generation product.
