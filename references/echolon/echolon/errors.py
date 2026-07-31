"""Echolon error hierarchy and catalog."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EchelonError(Exception):
    """Base class for all Echolon validation errors."""
    code: str
    what: str
    why: str
    fix: str
    context: dict[str, Any] = field(default_factory=dict)
    docs_url: str = ""

    def __str__(self) -> str:
        return (
            f"\n[{self.code}] {self.what}\n"
            f"  Why:     {self.why}\n"
            f"  Fix:     {self.fix}\n"
            f"  Context: {self.context}\n"
            f"  Docs:    {self.docs_url}\n"
        )


@dataclass
class ValidationError(EchelonError):
    """Validation / type errors (VAL-xxx)."""


@dataclass
class ConfigError(EchelonError):
    """Config errors (CFG-xxx)."""


@dataclass
class StrategyStructureError(EchelonError):
    """Strategy directory structure errors (STR-xxx)."""


@dataclass
class IndicatorError(EchelonError):
    """Indicator name / casing errors (IND-xxx)."""


@dataclass
class ParameterError(EchelonError):
    """Parameter framework errors (PRM-xxx)."""


@dataclass
class DataError(EchelonError):
    """Data loading / file errors (DAT-xxx)."""


# =============================================================================
# Error Catalog Registry
# =============================================================================

ERROR_CATALOG: dict[str, dict] = {
    "VAL-001": {
        "class": ValidationError,
        "what": "Missing required field in component output",
        "why": (
            "Echolon component contracts require all fields for downstream "
            "trade logging, regime evaluation, and backtest analysis."
        ),
        "fix_template": (
            "In {file}:{method}, add missing fields to the output object:\n"
            "  missing fields: {missing}\n"
            "See the component_guide skill for the full contract."
        ),
    },
    "VAL-002": {
        "class": ValidationError,
        "what": "Invalid enum value in signal field",
        "why": "Signal values must be 'LONG', 'SHORT', or 'HOLD'.",
        "fix_template": (
            "In {file}:{method}, use a valid signal value.\n"
            "  got: {got}\n"
            "  expected: 'LONG' | 'SHORT' | 'HOLD'"
        ),
    },
    "VAL-003": {
        "class": EchelonError,
        "what": "Required JSON key missing from expected artifact",
        "why": (
            "A validator that expected a JSON file to carry specific top-level "
            "keys (e.g., trial_number, params, metrics in "
            "selected_robust_trial.json) found the file but not the keys. The "
            "artifact may be corrupt, truncated, or from a different stage."
        ),
        "fix_template": (
            "Inspect the artifact and verify the producing stage ran to completion:\n"
            "  file:             {file}\n"
            "  missing_keys:     {missing_keys}\n"
            "  present_keys:     {present_keys}"
        ),
    },
    "VAL-005": {
        "class": EchelonError,
        "what": "Component method signature doesn't match protocol",
        "why": (
            "A component class (entry_rule / exit_rule / risk_manager / "
            "position_sizer) defines its required method but with arguments "
            "that don't match the protocol. The strategy will fail at "
            "engine binding time."
        ),
        "fix_template": (
            "Align the signature with the protocol:\n"
            "  component:        {component}\n"
            "  method:           {method}\n"
            "  expected:         {expected}\n"
            "  actual:           {actual}"
        ),
    },
    "VAL-006": {
        "class": EchelonError,
        "what": "Component method's return-type annotation is wrong",
        "why": (
            "A component method declares a return-type annotation, but it "
            "doesn't match the expected BaseModel (EntrySignalOutput / "
            "ExitSignalOutput / etc.). At runtime the strategy would either "
            "fail Pydantic validation or emit the wrong schema to downstream "
            "logging/analytics."
        ),
        "fix_template": (
            "Update the annotation to the expected BaseModel:\n"
            "  component:         {component}\n"
            "  method:            {method}\n"
            "  expected_return:   {expected_return}\n"
            "  actual_annotation: {actual_annotation}"
        ),
    },
    "CFG-001": {
        "class": ConfigError,
        "what": "end_date before start_date",
        "why": "Backtest date range is invalid.",
        "fix_template": (
            "Set end_date to a date after start_date.\n"
            "  start_date: {start_date}\n"
            "  end_date:   {end_date}"
        ),
    },
    "CFG-002": {
        "class": ConfigError,
        "what": "Required directory does not exist",
        "why": "Echolon cannot read from a path that doesn't exist.",
        "fix_template": (
            "Create the directory or update your config:\n"
            "  missing path: {path}\n"
            "  field:        {field}"
        ),
    },
    "CFG-003": {
        "class": ConfigError,
        "what": "Required path config not injected",
        "why": (
            "Echolon library functions no longer fall back to "
            "PathsConfig.from_env(); the caller must inject the directory "
            "explicitly. This prevents silent reliance on cwd / env vars."
        ),
        "fix_template": (
            "Construct one PathsConfig at program startup and pass the "
            "appropriate field through:\n"
            "  function: {function}\n"
            "  missing:  {param} (e.g. paths.{paths_field})"
        ),
    },
    "STR-001": {
        "class": StrategyStructureError,
        "what": "Strategy directory missing required file",
        "why": "Every Echolon strategy needs 6 files for the loader to work.",
        "fix_template": (
            "Add the missing file to {strategy_dir}:\n"
            "  missing: {missing_files}\n"
            "See `echolon init <dir> --template minimal` for a working example."
        ),
    },
    "STR-002": {
        "class": StrategyStructureError,
        "what": "Required class not found in file",
        "why": (
            "Echolon loads components by exact class name. Class name must "
            "match the file's expected export."
        ),
        "fix_template": (
            "In {file}, rename the class to {expected_class}.\n"
            "Found: {found_classes}"
        ),
    },
    "STR-003": {
        "class": StrategyStructureError,
        "what": "Required method not implemented",
        "why": "Component base classes require specific abstract methods.",
        "fix_template": (
            "In {file}.{class_name}, implement method: {missing_method}\n"
            "See the component_guide skill for signatures."
        ),
    },
    "IND-001": {
        "class": IndicatorError,
        "what": "Indicator name casing mismatch between code and JSON",
        "why": (
            "Indicator column names are lowercase in pre-computed data. "
            "Using uppercase in code causes silent KeyError or NaN at runtime."
        ),
        "fix_template": (
            "Change code to use lowercase indicator name:\n"
            "  code uses: {code_name}\n"
            "  should be: {json_name}\n"
            "See the patterns skill for naming rules."
        ),
    },
    "IND-002": {
        "class": IndicatorError,
        "what": "Indicator referenced in code but not declared in JSON",
        "why": (
            "strategy_indicator_list.json declares which indicators to "
            "pre-compute. Code must only use declared indicators."
        ),
        "fix_template": (
            "Add {indicator} to strategy_indicator_list.json, or remove its "
            "usage from {file}:{line}."
        ),
    },
    "PRM-001": {
        "class": ParameterError,
        "what": "Missing 'printlog' key in component params",
        "why": (
            "Parameter framework requires 'printlog': False in every "
            "component sub-dict. Omitting it causes validation to fail."
        ),
        "fix_template": (
            "In {file}:{function}, add 'printlog': False to {component_key}:\n"
            "  params[{component_key!r}] = {{'printlog': False, ...}}"
        ),
    },
    "PRM-002": {
        "class": ParameterError,
        "what": "Strategy params structure mismatch",
        "why": (
            "strategy_params.py must export DEFAULT_PARAMS as a dict with "
            "keys: entry_params, exit_params, risk_params, sizer_params."
        ),
        "fix_template": (
            "In {file}, DEFAULT_PARAMS must have shape:\n"
            "  {{'entry_params': {{...}}, 'exit_params': {{...}}, \n"
            "   'risk_params': {{...}}, 'sizer_params': {{...}}}}\n"
            "Missing keys: {missing_keys}"
        ),
    },
    "PRM-003": {
        "class": ParameterError,
        "what": "Hardcoded parameter value in component logic",
        "why": (
            "A numeric/string literal in a condition or threshold position "
            "was not sourced from self.params. The strategy cannot be "
            "Optuna-tuned at that threshold; the optimizer will walk past "
            "the real degree of freedom blindly."
        ),
        "fix_template": (
            "Move the literal into strategy_params and reference via self.<param>:\n"
            "  file:             {file}\n"
            "  line:             {line}\n"
            "  literal:          {literal}\n"
            "  suggestion:       {suggestion}"
        ),
    },
    "PRM-004": {
        "class": ParameterError,
        "what": "Defensive .get() on self.params",
        "why": (
            "Using self.params.get('x', default) masks missing-parameter "
            "bugs by silently falling back. Framework contract: every "
            "parameter declared in strategy_params.py is present on self, "
            "accessed via self.x — a missing param is a load-time error, "
            "not a runtime fallback."
        ),
        "fix_template": (
            "Replace with direct attribute access (self.x):\n"
            "  file:             {file}\n"
            "  line:             {line}\n"
            "  call:             {call}"
        ),
    },
    "PRM-005": {
        "class": ParameterError,
        "what": "Optimized trial parameters could not be resolved to the component vector",
        "why": (
            "best_trial could neither read a sha-verified resolved_params.json "
            "companion NOR replay the strategy dir's optuna_search_space to "
            "reproduce the optimizer-exact nested params. The lossy strip-once "
            "flat-name mapping was REMOVED (it silently orphaned prefixed-"
            "canonical params and dropped in-function shared copies), so rather "
            "than backtest on partially-correct parameters the run hard-fails."
        ),
        "fix_template": (
            "Make the dir's params resolvable, then re-run:\n"
            "  params_path:        {params_path}\n"
            "  strategy_code_dir:  {strategy_code_dir}\n"
            "Either (a) re-run trial selection to regenerate "
            "selected_robust_trial.json + its resolved_params.json companion, or "
            "(b) verify strategy_params.py imports cleanly and exposes "
            "optuna_search_space so on-demand replay can reproduce the vector."
        ),
    },
    "PRM-006": {
        "class": ParameterError,
        "what": "Parameter read via self.params['X'] but absent from DEFAULT_PARAMS",
        "why": (
            "A component reads self.params['<name>'] for a key that DEFAULT_PARAMS "
            "(strategy_params.py) does not declare — a guaranteed KeyError at "
            "bar-time, minutes into the backtest. Common cause: an EXPLOITATION "
            "value-tune regenerated the params file with only the tuned subset and "
            "dropped a fixed param the code still reads. Surfaced by "
            "validate_parameter_access — the self.params[...] reads are AST-scanned "
            "(all code paths); the declared key set is loaded at runtime from "
            "DEFAULT_PARAMS (which is composed dynamically, so it can't be parsed "
            "statically)."
        ),
        "fix_template": (
            "Declare the param in strategy_params.py (or carry it forward in the "
            "value-tune), or remove its read:\n"
            "  param: {param}\n"
            "  file:  {file}\n"
            "  line:  {line}"
        ),
    },
    "PRM-007": {
        "class": ParameterError,
        "what": "Search range drift between params_to_optimize.json and strategy_params.py",
        "why": (
            "A calculation/usage parameter's [min, max] search range in "
            "params_to_optimize.json differs from the matching trial.suggest_int/"
            "float range in strategy_params.py's optuna_search_space. Both are "
            "consumed: the .json range feeds the indicator-calc + Optuna search; "
            "optuna_search_space feeds the backtest. A value-tune that edits one "
            "but not the other makes the indicator-calc search a different range "
            "than the backtest optimizes — a silent inconsistency."
        ),
        "fix_template": (
            "Make the two ranges identical (edit .py and .json in sync):\n"
            "  param:      {param}\n"
            "  json_range: {json_range}\n"
            "  py_range:   {py_range}"
        ),
    },
    "PRM-008": {
        "class": ParameterError,
        "what": "Param declared in params_to_optimize.json absent from optuna_search_space",
        "why": (
            "A parameter declared in params_to_optimize.json (calculation/usage/"
            "fixed) has no entry in strategy_params.py's optuna_search_space — the "
            "two are out of sync, typically because a value-tune regenerated or "
            "edited strategy_params.py and dropped the param while the .json still "
            "declares it."
        ),
        "fix_template": (
            "Add the param to optuna_search_space (or remove it from "
            "params_to_optimize.json if intentionally gone):\n"
            "  param:   {param}\n"
            "  section: {section}.{sub}"
        ),
    },
    "DAT-001": {
        "class": DataError,
        "what": "Required OHLCV file not found",
        "why": "Echolon needs market data to run a backtest.",
        "fix_template": (
            "Expected file at: {path}\n"
            "Run data pipeline first or update market_data_dir in your config."
        ),
    },
    "DAT-002": {
        "class": DataError,
        "what": "State file is corrupt or unreadable JSON",
        "why": (
            "A live deploy reads strategy_state.json to resume position and "
            "cycle counters. A truncated or malformed file silently defaults "
            "to an empty state, losing position information mid-session."
        ),
        "fix_template": (
            "Inspect the state file and either repair it or delete it to "
            "cold-start:\n"
            "  path:       {path}\n"
            "  parse_error: {error}"
        ),
    },
    "DAT-003": {
        "class": DataError,
        "what": "Main contract data file not found for instrument",
        "why": (
            "Echolon resolves the main contract per trading date from "
            "market_data_dir/{exchange}/{symbol}/main_contract.csv. Without "
            "this file, contract rollover and live trading cannot proceed."
        ),
        "fix_template": (
            "Run the data pipeline once to populate main_contract.csv, "
            "or pass an explicit market_data_dir pointing at a populated tree.\n"
            "  expected:  {path}\n"
            "  symbol:    {symbol}"
        ),
    },
    "DAT-004": {
        "class": DataError,
        "what": "Trading calendar is empty after generation",
        "why": (
            "Calendar generation received zero valid rows. Either the input "
            "data has no date column, all dates are outside the requested "
            "range, or the source file is empty."
        ),
        "fix_template": (
            "Verify the upstream source has dated rows in the requested range:\n"
            "  market:      {market}\n"
            "  instrument:  {instrument}\n"
            "  start_date:  {start_date}\n"
            "  end_date:    {end_date}\n"
            "  rows_seen:   {rows_seen}"
        ),
    },
    "DAT-005": {
        "class": DataError,
        "what": "Unsupported OHLCV frequency parameter",
        "why": (
            "load_ohlcv accepts a frequency literal in {1d, 1m, 5m, 15m, 1h} "
            "per Q48 spec (qorka 2026-05-13). An unrecognized value would "
            "resolve to a path that doesn't exist; failing early with a "
            "clear error is preferable to a confusing DAT-001 not-found."
        ),
        "fix_template": (
            "Pass a frequency value that matches the supported set:\n"
            "  passed:    {frequency}\n"
            "  supported: {supported}\n"
            "Adjust the caller, or extend SUPPORTED_FREQUENCIES + storage "
            "convention if a new frequency tier is needed."
        ),
    },
    "IND-003": {
        "class": IndicatorError,
        "what": "Indicator column produced more NaN than warmup requires",
        "why": (
            "The indicator was requested with a period that exceeds the "
            "available bar history. More than the warmup-plus-some-headroom "
            "rows are NaN, which silently breaks downstream strategies that "
            "compare the column against thresholds."
        ),
        "fix_template": (
            "Either shorten the indicator period or extend the backtest "
            "start date to allow warmup:\n"
            "  indicator:  {indicator}\n"
            "  period:     {period}\n"
            "  rows:       {rows}\n"
            "  nan_rows:   {nan_rows}\n"
            "  nan_ratio:  {nan_ratio:.1%}"
        ),
    },
    "IND-004": {
        "class": IndicatorError,
        "what": "Regime optimizer returned a degenerate best-trial",
        "why": (
            "Every Optuna trial violated at least one hard constraint "
            "(min_ranging_pct / min_trending_pct / etc.), so the best-trial "
            "is the first-evaluated arbitrary trial, not a validated result. "
            "Deploying these params is unsafe."
        ),
        "fix_template": (
            "Loosen constraints in RegimeOptimizerConfig, or increase the "
            "historical window so the optimizer has enough regime-segments "
            "to satisfy constraints:\n"
            "  n_trials:          {n_trials}\n"
            "  trials_rejected:   {trials_rejected}\n"
            "  rejected_reasons:  {rejected_reasons}"
        ),
    },
    "IND-005": {
        "class": IndicatorError,
        "what": "Calculator received a DataFrame without a required column",
        "why": (
            "Indicator calculators have explicit column contracts (e.g., a "
            "session-phase indicator requires 'datetime' and 'trading_date'). "
            "Running the calculator on a DataFrame missing those columns "
            "silently produces all-NaN output in the best case, junk values "
            "in the worst."
        ),
        "fix_template": (
            "Ensure the input DataFrame has all required columns before "
            "calling the calculator:\n"
            "  calculator:         {calculator}\n"
            "  missing_column:     {missing_column}\n"
            "  required_columns:   {required_columns}\n"
            "  present_columns:    {present_columns}"
        ),
    },
    "IND-006": {
        "class": IndicatorError,
        "what": "strategy_indicator_list.json has an inverted [min, max] sweep range",
        "why": (
            "A parameter's sweep range is written as a two-element integer list "
            "[min, max] with min > max. Optuna's suggest_int(low, high) requires "
            "low <= high, so the trial sampler raises on the first trial — the "
            "range is unusable as written. Emitted by validate_indicator_list "
            "(catalog range check), not raised at runtime."
        ),
        "fix_template": (
            "Swap the bounds in strategy_indicator_list.json so min <= max for "
            "the named field (e.g. [28, 14] -> [14, 28])."
        ),
    },
    "IND-007": {
        "class": IndicatorError,
        "what": "Component reads an indicator column not declared in strategy_indicator_list.json",
        "why": (
            "A component calls self.get_indicator(\"<name>\") for a column whose "
            "base indicator was never declared in strategy_indicator_list.json — a "
            "rename/typo drift between the JSON and the code (e.g. code reads "
            "'high_20' but the JSON declared 'highest_high'). The engine only "
            "computes declared indicators, so the lookup KeyErrors at runtime. "
            "Surfaced by the bar-0 component smoke (validate_component_smoke); not "
            "raised at module import or signature checks."
        ),
        "fix_template": (
            "Either rename the get_indicator() argument to a DECLARED column, or "
            "add the indicator to strategy_indicator_list.json:\n"
            "  undeclared_read: {indicator}\n"
            "  declared:        {declared}"
        ),
    },
    "IND-008": {
        "class": IndicatorError,
        "what": "Legacy section-keyed indicator-list format",
        "why": (
            "strategy_indicator_list.json must be a flat dict mapping each "
            "indicator name directly to its param spec. A top-level section "
            "wrapper (indicators_with_lookback / indicators_without_lookback / "
            "indicators_with_special_params / system_provided_indicators) is the "
            "deprecated format; the catalog validator would otherwise treat each "
            "section key as an indicator name and emit a junk IND-004 per section. "
            "Surfaced by validate_indicator_list (IndicatorCatalog.validate)."
        ),
        "fix_template": (
            "Flatten every section's entries up to the top level and drop the "
            "section wrappers, e.g.\n"
            '  {{"rsi": {{"timeperiod": [10, 20]}}, "obv": {{}}, "market_regime": {{}}}}\n'
            "  legacy sections found: {field}"
        ),
    },
    "IND-009": {
        "class": IndicatorError,
        "what": "curve_carry indicator requested from the single-frame compute path",
        "why": (
            "curve_carry indicators (carry_front_back, carry_z_3m, etc.) are built "
            "from the full multi-contract forward curve — every listed contract's "
            "term structure on a date — not one instrument's own OHLCV history. "
            "compute_indicators_from_frame takes a single caller-provided continuous "
            "OHLCV DataFrame and has no access to the other contracts on the curve, "
            "so it cannot reproduce these indicators; silently omitting or "
            "approximating them would be a misleading result for a caller expecting "
            "parity with the standard per-contract pipeline."
        ),
        "fix_template": (
            "Drop the curve_carry indicators from indicator_list before calling "
            "compute_indicators_from_frame, or compute them separately from the "
            "forward curve (echolon.indicators.calculators.interday.carry."
            "series_builder.build_carry_indicator_frame) and merge the columns in "
            "yourself:\n"
            "  offending: {indicators}"
        ),
    },
    "BT-001": {
        "class": EchelonError,
        "what": "Strategy.on_bar() raised an exception",
        "why": (
            "A strategy's entry/exit/risk/sizer component raised during a "
            "bar-level call. The exception was caught by the engine so the "
            "backtest could stop cleanly; the strategy code is the likely root cause."
        ),
        "fix_template": (
            "Open {file} at the component that raised and reproduce with "
            "the context below:\n"
            "  bar_index:       {bar_index}\n"
            "  trading_date:    {trading_date}\n"
            "  contract:        {contract}\n"
            "  position_size:   {position_size}\n"
            "  exception:       {exception_repr}"
        ),
    },
    "BT-002": {
        "class": EchelonError,
        "what": "Backtest produced zero trades",
        "why": (
            "The strategy ran through the configured period without firing "
            "a single entry. Common causes: entry conditions never met, "
            "filters block every signal, risk manager blocks every order."
        ),
        "fix_template": (
            "Inspect entry/filter/risk diagnostics printed above this error:\n"
            "  bars_processed:          {bars_processed}\n"
            "  entry_signals_generated: {entry_signals_generated}\n"
            "  entry_signals_blocked:   {entry_signals_blocked}\n"
            "  risk_blocks:             {risk_blocks}\n"
            "Call MCP get_error_doc('BT-002') (or read echolon/native/errors/codes/BT-002.md) for the decision tree."
        ),
    },
    "BT-003": {
        "class": EchelonError,
        "what": "Optuna trial violated a hard constraint",
        "why": (
            "The trial's param set produced regime metrics outside the "
            "viability bounds configured in RegimeOptimizerConfig. The "
            "trial's score is clamped to 0.0 so it will not be selected."
        ),
        "fix_template": (
            "Widen the constraint or the param range that triggered this:\n"
            "  trial_number:   {trial_number}\n"
            "  constraint:     {constraint}\n"
            "  required:       {required}\n"
            "  actual:         {actual}\n"
            "  params:         {params}"
        ),
    },
    "BT-010": {
        "class": EchelonError,
        "what": "Required log marker absent from backtest output",
        "why": (
            "A debug-completion check expected a specific marker substring "
            "(e.g., 'STAGE 4 COMPLETE', 'FINAL SUCCESS') in the backtest "
            "log, meaning the producing stage ran to completion. Marker is "
            "missing — the stage either failed or was skipped."
        ),
        "fix_template": (
            "Inspect the log around the last completed stage:\n"
            "  log_path:         {log_path}\n"
            "  missing_marker:   {missing_marker}\n"
            "  last_marker_seen: {last_marker_seen}"
        ),
    },
    "LIV-001": {
        "class": EchelonError,
        "what": "Broker connection unavailable",
        "why": (
            "The QMT/CCXT client lost connection or failed to initialize. "
            "Trading is halted; no orders will be submitted until the "
            "connection is restored."
        ),
        "fix_template": (
            "Restore the broker connection and restart the runner:\n"
            "  platform:     {platform}\n"
            "  account_id:   {account_id}\n"
            "  error:        {error}"
        ),
    },
    "LIV-002": {
        "class": EchelonError,
        "what": "Order rejected by broker",
        "why": (
            "The broker rejected an order. Common causes: price outside the "
            "day's range, insufficient margin, invalid contract code, "
            "direction/size mismatch."
        ),
        "fix_template": (
            "Inspect the rejected order and broker response:\n"
            "  contract:       {contract}\n"
            "  direction:      {direction}\n"
            "  price:          {price}\n"
            "  size:           {size}\n"
            "  broker_status:  {broker_status}\n"
            "  broker_message: {broker_message}"
        ),
    },
    "WFA-001": {
        "class": EchelonError,
        "what": "WFA pipeline produced zero valid trials across all windows",
        "why": (
            "Every walk-forward window ran its Optuna optimization but "
            "produced no successful trials. This is almost always a strategy "
            "or configuration bug rather than a market-fit issue — the same "
            "error is repeating on every trial. Per-window "
            "trial_failure_summary.json artifacts carry the structured root "
            "cause for each window."
        ),
        "fix_template": (
            "Inspect per-window trial_failure_summary.json artifacts:\n"
            "  n_windows:           {n_windows}\n"
            "  reason:              {reason}\n"
            "  per_window_artifacts: {suggestion}"
        ),
    },
    "WFA-002": {
        "class": EchelonError,
        "what": "WFA pipeline completed only some of its walk-forward windows",
        "why": (
            "Some — but not all — walk-forward windows produced a robust "
            "trial; the remaining windows found zero surviving trials and were "
            "skipped. Proceeding would run the final full-period backtest with "
            "the LAST-COMPLETED window's parameters silently reused over the "
            "whole history, and score the DRS gates on the shrunken set of "
            "completed windows — a plausible-but-wrong verdict. An incomplete "
            "WFA cannot be scored. The failed windows carry their structured "
            "root cause in per-window trial_failure_summary.json."
        ),
        "fix_template": (
            "Inspect the failed windows' trial_failure_summary.json artifacts:\n"
            "  windows_completed:    {n_completed} / {n_total}\n"
            "  failed_windows:       {failed_windows}\n"
            "  per_window_artifacts: {suggestion}"
        ),
    },
    "LIV-003": {
        "class": EchelonError,
        "what": "QMT async callback delivered an error",
        "why": (
            "The miniQMT xtconstant callback for order/trade status indicated "
            "a failure outcome. The callback thread logs this but the main "
            "loop needs to translate it for the LLM agent monitoring the run."
        ),
        "fix_template": (
            "Translate the QMT status code and follow broker-specific remediation:\n"
            "  seq_id:       {seq_id}\n"
            "  qmt_status:   {qmt_status}\n"
            "  echo_status:  {echo_status}\n"
            "  raw:          {raw}"
        ),
    },
}


def raise_error(code: str, **context_vars: Any) -> None:
    """Raise an EchelonError by code with context formatted into fix template."""
    entry = ERROR_CATALOG[code]
    try:
        fix = entry["fix_template"].format(**context_vars)
    except KeyError:
        fix = entry["fix_template"]
    raise entry["class"](
        code=code,
        what=entry["what"],
        why=entry["why"],
        fix=fix,
        context=dict(context_vars),
        docs_url=f"https://github.com/dolphinquant/echolon/blob/master/echolon/native/errors/codes/{code}.md",
    )
