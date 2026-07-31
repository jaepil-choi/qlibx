---
name: component_guide
description: Per-component contract — entry_rule / exit_rule / risk_manager / position_sizer / strategy_main. Class names, method signatures, return types, when each is called. Use when authoring or debugging a strategy component.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: phase_f9b_docs_migration
---

# Component Guide

Every echolon strategy has **5 components** the loader binds by name (`entry_rule`, `exit_rule`, `risk_manager`, `position_sizer`, `strategy_main`). Class names are exact — `StrategyLoader` looks them up by string. See the `strategy_loader` skill for binding details, and the `trading-api-core` skill for indicator-naming and BaseModel-output rules that apply across all components.

## entry_rule (entry.py)

- **Class name**: `entry_rule` (exact — required by StrategyLoader)
- **Base**: `BaseComponent`
- **Method**: `generate_signal() -> EntrySignalOutput`
- **Called**: every bar when there is no open position and no pending orders.

```python
from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import OrderIntent
from echolon.strategy.schemas import EntrySignalOutput


class entry_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
        self.rsi_period = self.params["rsi_period"]

    def generate_signal(self) -> EntrySignalOutput:
        rsi = self.get_indicator(f"rsi_{self.rsi_period}")
        if rsi < 30:
            return EntrySignalOutput(
                signal="LONG", strength=1.0,
                type="oversold_entry",
                entry_reason=f"RSI({self.rsi_period})={rsi} < 30",
                intent=OrderIntent.ENTRY_LONG,
            )
        return EntrySignalOutput(
            signal="HOLD", strength=0.0, type="hold",
            entry_reason="Not oversold",
        )
```

Common errors: `VAL-001` (missing required field), `VAL-005`/`VAL-006` (wrong signature/return annotation), `IND-001` (uppercase indicator name).

## exit_rule (exit.py)

- **Class name**: `exit_rule`
- **Base**: `BaseComponent`
- **Method**: `should_exit() -> ExitSignalOutput`
- **Called**: every bar when there is an open position.

Stateful exit rules (trailing stops, bars-held counters) must reset their state when `pos.size == 0`. See the bundled `minimal` template's `exit.py` for the canonical reset pattern.

## risk_manager (risk.py)

- **Class name**: `risk_manager`
- **Base**: `BaseComponent`
- **Method**: `can_trade() -> RiskOutput`
- **Called**: at the start of every bar.

Returns `trading_allowed=True` to permit trading, `False` to block all new entries (existing positions are unaffected — they exit by their own rule). Use cases: max daily loss, max consecutive losses, trading-hours filter.

## position_sizer (sizer.py)

- **Class name**: `position_sizer`
- **Base**: `BaseComponent`
- **Method**: `calculate_size(signal_data: EntrySignalOutput) -> SizerOutput`
- **Called**: after `entry_rule.generate_signal()` produces a non-HOLD signal.

The sizer receives the signal (so it can branch on `signal_data.regime`, `signal_data.strength`, etc.). It **MUST** call `self.validate_and_convert_position_size(raw_float)` before setting `calculated_size` — this rounds to whole contracts and handles edge cases.

## Data access helpers

All components inherit these helpers from `BaseComponent`:

- `self.get_current_price() -> float` — close of current bar
- `self.get_indicator(name: str) -> float` — value of pre-computed indicator (lowercase names; raises `KeyError` on miss — let it propagate per the No-Error-Handling Policy in `trading-api-core`)
- `self.get_market_regime() -> str` — labels are **classifier-defined**. Echolon ships no built-in classifier; the host application registers one via `echolon.indicators.registry.register_regime_classifier(...)`. Calling `get_market_regime()` without a registered classifier raises. Plain technical strategies don't need this helper.
- `self.params: dict` — kwargs from `strategy_params.py:DEFAULT_PARAMS[<component>_params]`. Access via `self.params["x"]` in `__init__`, then assign to a typed attribute (`self.x = self.params["x"]`). NEVER `self.params.get("x", default)` — see `PRM-004`.
- `self.portfolio: IPortfolio` — access position info (`portfolio.get_position()` returns `Position | None`)
- `self.validate_and_convert_position_size(float) -> int` — sizer helper (rounds to whole contracts)

## Strategy coordinator (strategy.py)

- **Class name**: `strategy_main`
- **Base**: `BaseStrategy`
- **Method**: `_execute_bar() -> None` — **NOT** `on_bar`. `on_bar()` is the framework's Template Method that calls `_execute_bar()` after running pre-bar hooks (contract rollover, session filters); strategies override `_execute_bar()` only.

The canonical pattern (used by every bundled template — only customize if you truly need a different structure):

```python
def _execute_bar(self) -> None:
    risk_out = self.risk_manager.can_trade()
    if not risk_out.trading_allowed:
        return
    if self.has_position() and not self.has_pending_orders():
        exit_out = self.exit_rule.should_exit()
        if exit_out.should_exit and exit_out.intent is not None:
            self.exit(exit_out.intent)
            return
    if not self.has_position() and not self.has_pending_orders():
        entry_out = self.entry_rule.generate_signal()
        if entry_out.signal != "HOLD" and entry_out.intent is not None:
            sizer_out = self.position_sizer.calculate_size(entry_out)
            if sizer_out.calculated_size > 0:
                self.entry(entry_out.intent, sizer_out.calculated_size)
```

## See also

- Skill: `trading-api-core` — indicator-naming rules + BaseModel output contract + No-Error-Handling Policy
- Skill: `parameter-patterns` — how `strategy_params.py` is wired
- Skill: `strategy_loader` — how `StrategyLoader` finds these classes
- MCP tool: `scaffold_component(kind, strategy_dir)` — emit framework-correct stubs
