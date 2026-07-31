# Platform Architecture

## Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    PLATFORM LAYER                               │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Backtrader Platform    │    MiniQMT Platform               ││
│  │ • BacktraderTradingEngine  • QMTTradingEngine              ││
│  │ • Platform-specific adapters and implementations           ││
│  └─────────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────┤
│             PLATFORM-AGNOSTIC STRATEGY LAYER                    │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │    Strategy Components (Pure Trading Logic)                ││
│  │  • entry.py  • exit.py  • risk.py  • sizer.py             ││
│  │  • strategy.py (main coordinator)                          ││
│  └─────────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────┤
│                  ABSTRACTION LAYER                              │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │           Core Interfaces & Base Classes                   ││
│  │  • ITradingEngine  • BaseStrategy  • BaseComponent         ││
│  │  • IMarketData     • IPortfolio    • IOrderManager         ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## Key Principles

1. **Platform Independence**: Strategy components use only abstract interfaces
2. **Component Specialization**: Each component handles one aspect (entry, exit, risk, sizing)
3. **No Error Handling**: All errors propagate explicitly (no try-except)
4. **Configurable Parameters**: All thresholds loaded from parameters
5. **Standardized Output**: All components return BaseModel instances

## File Organization

Strategy files live in any directory on disk and are loaded by echolon via
`StrategyLoader(strategy_dir).load_module("<name>")`. Host apps choose the
directory location; no fixed filesystem path.

**Conventional layout** (`echolon init` / `echolon hello` scaffold here; host apps may override via the workspace marker's `paths` field):

```
workspace/strategy/baseline/
├── entry.py              # Entry signal generation
├── exit.py               # Exit decision logic
├── risk.py               # Risk management
├── sizer.py              # Position sizing
├── strategy.py           # Main coordinator (strategy_main class)
├── strategy_params.py    # Parameter definitions
└── strategy_indicator_list.json  # Flat-dict indicator configuration
```

**Required files** (per `echolon/strategy/preflight.py::REQUIRED_FILES`):
`entry.py`, `exit.py`, `risk.py`, `sizer.py`,
`strategy_params.py`, `strategy_indicator_list.json`. (`strategy.py` is
required in practice — loaded separately by
`StrategyLoader.load_function("strategy", "strategy_main")` — but it is
not in preflight's list.) `BaseComponent` lives in the installed package
at `echolon.strategy.component`; strategies import it, they do not ship a
local copy.

**Required class exports** (per `echolon/strategy/loader.py::_REQUIRED_CLASSES`):

| File | Class name |
|---|---|
| `entry.py` | `entry_rule` |
| `exit.py` | `exit_rule` |
| `risk.py` | `risk_manager` |
| `sizer.py` | `position_sizer` |

`strategy.py`'s class must be named `strategy_main` (loaded via
`StrategyLoader.load_function("strategy", "strategy_main")` — loader.py:13).

## Component Flow

```
┌────────────────────────────────────────────────────────────────┐
│  BaseStrategy._execute_bar()                                   │
│  (override target — NOT on_bar(), which is a Template Method   │
│   orchestrating hook lifecycle; see echolon/strategy/base.py)  │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ risk_manager         │
                │   .can_trade()       │──► RiskOutput
                └──────────┬───────────┘
                           │
     ┌─────────────────────┴─────────────────────┐
     │        has_position()?                    │
     ▼                                           ▼
┌─────────────────────────┐          ┌───────────────────────────┐
│ Flat + trading_allowed: │          │ In position:              │
│   entry_rule            │          │   exit_rule               │
│     .generate_signal()  │── ESO ──►│     .should_exit()        │── XSO
│   if signal != HOLD:    │          │   if should_exit:         │
│     position_sizer      │          │     self.exit(intent)     │
│       .calculate_size() │── SO ──► └───────────────────────────┘
│   if size > 0:          │
│     self.entry(...)     │
└─────────────────────────┘
  ESO = EntrySignalOutput
  SO  = SizerOutput
  XSO = ExitSignalOutput
```

**Key invariants:**

- `_execute_bar()` is the override target — never `on_bar()`. See
  `echolon/strategy/base.py:934` for the Template Method docstring: *"Do NOT
  override this method. Override _execute_bar() instead."*
- Risk check always runs first; `trading_allowed=False` blocks new entries
  but does NOT block exits on existing positions (exit logic still evaluates
  when in position — circuit breakers are the exception; see STRATEGY.md).
- Position-state branches: entry + sizer path fires only when **flat**; exit
  path fires only when **in position**. Exit never runs "after" entry in the
  same bar — they're mutually exclusive per-bar outcomes.
- Always guard order submission with `has_pending_orders()` — see
  STRATEGY.md for the full pattern (Backtrader orders execute at next bar's
  open; without this guard, consecutive bars produce massive over-sized
  positions).

## Documentation Hierarchy

Skills (shipped under `echolon/native/skills/echolon_api/` and reachable via the MCP `get_skill(name)` tool) illustrate patterns, interfaces, and examples. Authoritative trading logic and parameter values live in your strategy directory on disk (whatever path you point `StrategyLoader` at — `workspace/strategy/baseline/` is the conventional scaffold). When skill examples and on-disk code disagree, the on-disk code is the source of truth.
