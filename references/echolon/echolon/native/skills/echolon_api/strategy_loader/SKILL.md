---
name: strategy_loader
description: Unified on-disk strategy module loader — imports strategy.py / entry.py / exit.py / risk.py / sizer.py / strategy_params.py from any directory via importlib, resolving relative imports under a configurable package base and caching the loaded modules.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.strategy.loader.StrategyLoader

## Purpose

`StrategyLoader` is the one loading pattern echolon uses for strategy code that lives on disk — it replaces ad-hoc combinations of static imports, `importlib.import_module`, and `spec_from_file_location + manual __package__` with a single `importlib.util.spec_from_file_location`-based path that handles the tricky bits: assigning `__package__` so strategy code can use either absolute imports (canonical — e.g., `from echolon.strategy.base import BaseStrategy`) or legacy relative imports (for strategies archived before the v0.3 package rename, e.g., `from ...core.base.base_strategy import BaseStrategy`), registering the module in `sys.modules` under a fully-qualified name (`{package_base}.{module_name}`) so pickle can find it during multiprocessing, caching the module to avoid re-execution, and surfacing typed `EchelonError`s (via the paired `load_strategy_from_dir` helper) so LLM authors get actionable structural errors.

## Interface

```python
from pathlib import Path
from echolon.strategy.loader import StrategyLoader, load_strategy_from_dir

# 1. Basic: load an individual function / class / attribute from a strategy dir.
loader = StrategyLoader(Path("/workspace/strategy/baseline"))
strategy_main = loader.load_function("strategy", "strategy_main")
EntryRule     = loader.load_class("entry", "entry_rule")
search_space  = loader.load_attr("strategy_params", "optuna_search_space")

# 2. Custom package_base — useful when multiple slots share a process and you
#    need unique module identities for pickling.
loader = StrategyLoader(
    Path("/tmp/slot_3"),
    package_base="echolon.quant_engine.strategy._dynamic.slot_3",
)
strategy_main = loader.load_function("strategy", "strategy_main")

# 3. Cache management — call when files on disk were rewritten (e.g. by the
#    coding agent) and must be re-imported fresh.
loader.clear_cache()

# 4. Catalog-aware entry point: validates structure first, returns components.
components = load_strategy_from_dir("/workspace/strategy/baseline")
# -> {"entry_rule": EntryRule, "exit_rule": ExitRule,
#     "risk_manager": RiskManager, "position_sizer": PositionSizer}
```

## When to use

- Any time echolon loads strategy code from an arbitrary directory: `BacktraderStrategyBridge._initialize_strategy` uses `StrategyLoader(Path(code_dir))` to import `strategy.strategy_main`. Custom orchestrators that swap strategies between iterations should do the same.
- When strategy files are rewritten at runtime (the coding agent pattern): call `loader.clear_cache()` between iterations. Without that, `importlib` returns the cached module and your code changes won't take effect.
- As `load_strategy_from_dir(strategy_dir)` when you want structural validation: it runs `echolon.strategy.preflight.preflight(strategy_dir)` before loading, so the caller gets `STR-001` / `STR-002` / `PRM-001` / `PRM-002` instead of later `AttributeError`/`ImportError`.
- Do *not* use `importlib.import_module` against on-disk strategy paths that are not on `sys.path`. You lose the `__package__` assignment, relative imports break, and pickling under Optuna's `ProcessPoolExecutor` fails because the module is not findable from `sys.modules`.
- Do *not* bypass preflight for production code generation. Typed errors are the whole reason `load_strategy_from_dir` exists — the agent can self-correct when it sees `STR-001` but not when it sees an `AttributeError` with no echolon code.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `StrategyLoader(strategy_dir, package_base="echolon.quant_engine.strategy._dynamic")` | `Path`, optional package-base string | — | Instantiates the loader. No I/O yet. |
| `load_module(module_name)` | `str` (no `.py`) | `ModuleType` | Reads `{strategy_dir}/{module_name}.py`, assigns `__package__ = package_base`, registers under `sys.modules[f"{package_base}.{module_name}"]`, caches. Pops `sys.modules` entry on exec failure. |
| `load_attr(module_name, attr_name)` | strings | `Any` | `getattr(load_module(...), attr_name)`; raises `AttributeError` with a helpful path if missing. |
| `load_function(module_name, func_name)` | strings | `Any` | Alias for `load_attr`. |
| `load_class(module_name, class_name)` | strings | `type` | Alias for `load_attr`. |
| `clear_cache()` | — | — | Drops `self._cache`; pops every `sys.modules[f"{package_base}.{module_name}"]` so next load re-executes the source. |
| `has_module(module_name)` | `str` | `bool` | File-existence check. |
| `load_strategy_from_dir(strategy_dir, package_base="echolon.quant_engine.strategy._dynamic")` | `Path | str`, optional string | `dict[str, Any]` | Runs `_preflight(strategy_dir)` (echolon.strategy.preflight), then loads the 4 required component classes listed in `_REQUIRED_CLASSES`: `entry.entry_rule`, `exit.exit_rule`, `risk.risk_manager`, `sizer.position_sizer`. Returns the dict. |

`_REQUIRED_CLASSES` (module-level): `{"entry": "entry_rule", "exit": "exit_rule", "risk": "risk_manager", "sizer": "position_sizer"}`. Note that `strategy.py` and `strategy_params.py` are also required by preflight but their top-level symbols are not collected into the returned dict — callers load them separately via `loader.load_function("strategy", "strategy_main")` etc.

## Common errors

- **`FileNotFoundError: Strategy module not found: .../entry.py`** — `load_module` couldn't find the file. Usually a bad `strategy_dir` argument or an uninitialized workspace.
- **`AttributeError: Module 'strategy_params' in /path has no attribute 'optuna_search_space'`** — `load_attr` target missing. The file exists but the symbol isn't exported.
- **`STR-001`** (from `load_strategy_from_dir`) — a required file is missing. Full list per `echolon/strategy/preflight.py::REQUIRED_FILES`: `entry.py`, `exit.py`, `risk.py`, `sizer.py`, `strategy_params.py`, `strategy_indicator_list.json`. `strategy.py` is loaded separately via `loader.load_function("strategy", "strategy_main")` and is required in practice by the coordinator load path but not in preflight's list. `BaseComponent` ships in the installed package (`echolon.strategy.component`) — strategies import it, no per-strategy `component.py` exists. See `echolon/native/errors/codes/STR-001.md`.
- **`STR-002`** (from `load_strategy_from_dir`) — a required class is not exported by its module (e.g. `entry.py` without `entry_rule`). See `echolon/native/errors/codes/STR-002.md`.
- **`PRM-001` / `PRM-002`** (from `load_strategy_from_dir`) — `strategy_params.DEFAULT_PARAMS` is malformed (missing `printlog` or wrong structure). See `echolon/native/errors/codes/PRM-001.md`, `echolon/native/errors/codes/PRM-002.md`.
- **Stale cache after file rewrite** — subsequent `load_*` calls return the previous module contents. Call `clear_cache()` between iterations.
- **`ImportError: attempted relative import beyond top-level package`** — strategy code used more leading dots (`from ....x.y import z`) than the `package_base` allows. Lengthen the `package_base` or flatten the import.
- **Pickle failure under multiprocessing** — only happens if `sys.modules` registration was skipped. `StrategyLoader` does it for you; don't bypass `load_module` to import the file by hand.

## See also

- `get_strategy_class` skill — `BacktraderStrategyBridge._initialize_strategy` uses a `StrategyLoader` instance to import `strategy.strategy_main`.
- echolon docs: `echolon/strategy/preflight.py` (`preflight`), `echolon/native/errors/codes/STR-001.md`, `echolon/native/errors/codes/STR-002.md`, `echolon/native/errors/codes/PRM-001.md`, `echolon/native/errors/codes/PRM-002.md`.
- `run_best_trial` skill — indirect consumer via `BacktestRunner.best_trial → BacktraderStrategyBridge → StrategyLoader`.
