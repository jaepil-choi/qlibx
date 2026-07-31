---
name: api_reference
description: Public class signatures echolon exposes — configs (BacktestConfig / OptunaConfig / IndicatorConfig / TradingContext), component output schemas (EntrySignalOutput / ExitSignalOutput / RiskOutput / SizerOutput), enums (OrderIntent), and the EchelonError hierarchy. Use when you need a typed signature lookup.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: phase_f9b_docs_migration
---

# API Reference

Public-surface signatures, in the form an agent needs to construct calls. For deeper per-class doctrine see the dedicated skills (`market_factory`, `engine_factory`, etc.). For runtime introspection use `echolon schema <type>` or `model_json_schema()` on the Pydantic class.

## BacktestConfig

**Module**: `echolon.config.backtest_config`
**Purpose**: configuration for a single backtest run.

```python
BacktestConfig(
    start_date: str,            # "YYYY-MM-DD"
    end_date: str,              # "YYYY-MM-DD"
    strategy_dir: Path,
    market_data_dir: Path,
    indicator_dir: Path,
    results_dir: Path,
    max_drawdown_pct: float = 15.0,
    is_end_date: Optional[str] = None,
    oos_start_date: Optional[str] = None,
    market_research_end_date: Optional[str] = None,
)
```

Common errors: `CFG-001`, `CFG-002`.

## OptunaConfig

**Module**: `echolon.config.optuna_config`
**Purpose**: Optuna hyperparameter search settings.

```python
OptunaConfig(
    n_trials: int = 100,
    n_jobs: int = -1,
    timeout: Optional[int] = None,
    target: Literal["sharpe_ratio", "total_return", "annual_return", "drawdown", "multi_objective"] = "sharpe_ratio",
    n_trials_debug: int = 20,
    aggressive_memory_management: bool = False,
    enhanced_monitoring: bool = True,
)
```

## IndicatorConfig

**Module**: `echolon.config.indicator_config`
**Purpose**: per-frequency period caps consulted by `generate_strategy_params` auto-clamp logic. Most users never override.

```python
IndicatorConfig(
    interday_caps: dict[str, int],
    intraday_caps: dict[str, int],
)
```

## TradingContext

**Module**: `echolon.config.markets.core.context`
**Purpose**: market + instrument + frequency + bar_size runtime context. Build via `MarketFactory.create(...)` (don't construct directly). See the `market_factory` skill.

```python
MarketFactory.create(
    market: str,           # e.g., "SHFE"
    instrument: str,       # e.g., "cu"
    frequency: str,        # "interday" | "intraday"
    bar_size: str,         # e.g., "1d", "5m"
    initial_capital: float = 200000.0,
) -> TradingContext
```

## quick_start()

**Module**: `echolon` (top-level export)
**Purpose**: build sensible default configs for common cases.

```python
from echolon import quick_start

ctx, bt, opt = quick_start(
    market="shfe",
    instrument="cu",
    start_date="2020-01-01",
    end_date="2023-12-31",
)
```

Returns `(TradingContext, BacktestConfig, OptunaConfig)`. Override fields after construction.

## Component output schemas

All four BaseModels live in `echolon.strategy.schemas`. See the `component_guide` and `trading-api-core` skills for the methods that return them.

### EntrySignalOutput

Returned by `entry_rule.generate_signal()`.

- **Required**: `signal: Literal['LONG', 'SHORT', 'HOLD']`, `strength: float (0..1)`, `type: str`, `entry_reason: str`
- **Optional**: `intent: Optional[OrderIntent]` (required for non-HOLD), `regime: Optional[str]` (TRS-paradigm strategies populate; defaults to `None`)
- Common errors: `VAL-001`, `VAL-002`

### ExitSignalOutput

Returned by `exit_rule.should_exit()`.

- **Required**: `should_exit: bool`, `exit_reason: str`, `position_size: float (≥ 0)`, `bars_since_entry: int (≥ 0)`
- **Optional**: `intent: Optional[OrderIntent]` (required when `should_exit=True`), `signal: Optional[Literal['LONG', 'SHORT', 'HOLD']]` (echoes the originating entry signal when relevant; defaults to `None`)

### RiskOutput

Returned by `risk_manager.can_trade()`.

- **Required**: `trading_allowed: bool`, `risk_reason: str`

### SizerOutput

Returned by `position_sizer.calculate_size(signal_data)`.

- **Required**: `calculated_size: int (≥ 0, whole contracts)`, `signal_direction: Literal['LONG', 'SHORT', 'HOLD']`, `sizing_reason: str`, `raw_size: float (≥ 0)`

## OrderIntent (enum)

**Module**: `echolon.strategy.interfaces`

Values: `ENTRY_LONG`, `ENTRY_SHORT`, `EXIT_LONG`, `EXIT_SHORT`, `FORCED_EXIT`, `ROLLOVER_CLOSE`, `ROLLOVER_OPEN`.

## EchelonError hierarchy

**Module**: `echolon.errors` (root export). Base class for every structured echolon error. Each instance carries `code`, `what`, `why`, `fix`, `context`, `docs_url`.

Subclasses:

- `ValidationError` (VAL-xxx)
- `ConfigError` (CFG-xxx)
- `StrategyStructureError` (STR-xxx)
- `IndicatorError` (IND-xxx)
- `ParameterError` (PRM-xxx)
- `DataError` (DAT-xxx)

For the full catalog of codes + per-code documentation, call MCP `get_error_doc(code)` or read `echolon/native/errors/codes/{code}.md` in the installed package.

## See also

- CLI: `echolon schema BacktestConfig` (or any other Pydantic config) dumps full JSON schema
- Skill: `config_reference` — fields, defaults, env vars, PathsConfig
- Skill: `component_guide` — when each component method is called
- Skill: `trading-api-core` — indicator naming + No-Error-Handling Policy
