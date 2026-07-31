---
name: generate_strategy_params
description: Deterministic code generation of strategy_params.py from params_to_optimize.json — parses the JSON, determines parameter ownership across entry/exit/risk/sizer components, auto-clamps over-cap period values, and writes a complete strategy_params.py with ComponentParameterTemplate classes + optuna_search_space. Exposed as the echolon-mcp `generate_strategy_params` tool.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: params_generator_mcp_tool
---

# echolon.strategy.generators.generate_strategy_params

## Purpose

`generate_strategy_params(params_file_path, output_path, frequency="interday", indicator_config=None)` runs a 100%-deterministic code-generation pipeline that converts a `params_to_optimize.json` file into a complete `strategy_params.py` module. Given identical input, it produces identical output — no LLM inference, no randomness.

**What it produces** — a Python file containing:
- One `ComponentParameterTemplate` subclass per component (`EntryParameters`, `ExitParameters`, `RiskParameters`, `SizerParameters`), each with its `ParameterSpec` list.
- A `StrategyParameterFramework` initialization block that registers the four components.
- A module-level `DEFAULT_PARAMS` dict built from the framework.
- Helper functions `get_shared_params_mapping()` + `apply_shared_params(params)` for cross-component parameter copying.
- An `optuna_search_space(trial)` function with dependency-ordered `trial.suggest_*` calls, shared-parameter copying, and crossover constraints (prevents `short >= long` in period pairs).

**What it does NOT do** — it doesn't call an LLM, doesn't run Optuna, doesn't execute any backtest. It's a pure source-to-source transformer.

## Interface

### Python (library)

```python
from echolon.strategy.generators import generate_strategy_params, GenerationResult

result: GenerationResult = generate_strategy_params(
    params_file_path="/abs/path/to/params_to_optimize.json",
    output_path="/abs/path/to/workspace/strategy/baseline/strategy_params.py",
    frequency="interday",
)

if not result.success:
    raise RuntimeError(result.message)

for correction in result.corrections:
    print(f"Auto-clamped {correction['param']}: {correction.get('changes', [])}")
```

`GenerationResult` fields:
- `success: bool`
- `output_path: str` — absolute path of the written file (target path on failure).
- `corrections: list[dict]` — one entry per auto-clamped parameter (see Caps section).
- `message: str` — human-readable summary / error.

### MCP (echolon-mcp stdio tool)

```
tool: generate_strategy_params
args:
  params_file_path: str   # absolute path
  output_path:      str   # absolute path
  frequency:        str   # "interday" | "intraday"  (default "interday")

returns: {
  "success": bool,
  "output_path": str,
  "corrections": [{"param", "type", "old_*", "new_*", "cap", "category", "changes"?}, ...],
  "message": str,
}
```

Parse failures / missing input files / runtime errors surface as `success=false` with a descriptive `message` — the tool never raises through the MCP transport.

## When to use

- An upstream pipeline (host-app codegen, hand-edit, or strategy-design agent) has produced `params_to_optimize.json` and the next step is to compile it into a runnable `strategy_params.py` next to the strategy components.
- A parameter refinement pass edited `params_to_optimize.json` and needs to regenerate the downstream Python.
- CI / deterministic reproduction — given the same params JSON, regenerate the Python file byte-for-byte (for diff-based change review).

## When NOT to use

- If the goal is to *modify individual parameter values* at runtime — use `DEFAULT_PARAMS` + `apply_shared_params` directly in the already-generated module.
- If the caller wants an LLM to reason about parameter selection — this generator is purely mechanical; use a separate reasoning step upstream.

## Input contract

The `params_to_optimize.json` must have four top-level component sections plus a report:

```json
{
  "entry_parameters":  { "calculation": {...}, "usage": {...}, "fixed": {...} },
  "exit_parameters":   { "calculation": {...}, "usage": {...}, "fixed": {...} },
  "risk_parameters":   { "calculation": {...}, "usage": {...}, "fixed": {...} },
  "sizing_parameters": { "calculation": {...}, "usage": {...}, "fixed": {...} },
  "extraction_report": { "shared_parameters": [...] }
}
```

Per-parameter spec (inside `calculation` / `usage`):
```json
"rsi_period": {
  "type": "int",
  "range": [10, 20],
  "default": 14,
  "description": "RSI lookback window",
  "ownership": "owner"
}
```

Or for `fixed` section:
```json
"take_profit_pct": {
  "type": "float",
  "value": 0.05,
  "description": "Take profit at 5%",
  "ownership": "owner"
}
```

`ownership` is either `"owner"` (this component owns the param) or `"shared"` (references the owner's value). Cross-name shared parameters (e.g. `sizer_atr_period` shares `exit_atr_period`) are declared in `extraction_report.shared_parameters` with entries like `{"param": "exit_atr_period → sizer_atr_period", "owner": "exit", "shared_by": ["sizing"]}`.

## Period caps and auto-correction

Period parameters (name ending with `_period`) are auto-clamped to indicator-specific caps to prevent NaN-dominated indicator columns → zero-trade backtests. Caps are frequency-aware:

| Indicator tier | Interday cap (days) | Intraday cap (bars) | Rationale |
|---|---|---|---|
| TEMA / TRIX / ADXR | 62 | 500 | Cascading lookbacks (TEMA = EMA(EMA(EMA)) ≈ 3× effective period) |
| ADX / DEMA | 93 | 750 | Multi-stage smoothing |
| Default (all others) | 180 | 1000 | Conservative ceiling for single-pass indicators |

**How clamping works:**
- If `max > cap`, clamp `max` down to cap.
- If `min >= max` after clamping, repair the range (either lower `min` to `max(10, cap // 3)` or extend `max` to `min(original_min * 5, cap)`).
- Fixed values above the cap are clamped directly.
- `default` is pulled back into the corrected range.

Each correction appends an entry to `result.corrections`:

```python
{
    "param": "tema_period",
    "type": "range",                       # or "fixed_value"
    "old_range": [30, 120],
    "new_range": [30, 62],
    "old_default": 60,
    "new_default": 60,
    "cap": 62,
    "category": "TEMA/TRIX/ADXR",
    "changes": ["max_value: 120 → 62"],
}
```

Callers (or the calling LLM) should surface these corrections — the generated code reflects the clamped values, not the proposed ones, which may differ from what `params_to_optimize.json` declared.

## Common failure modes

| Symptom (`result.message`) | Cause | Fix |
|---|---|---|
| `Input file not found: ...` | `params_file_path` doesn't exist | Confirm whatever upstream tool / agent should have written the file actually did; check absolute path |
| `Failed to parse JSON in ...` | Malformed JSON | Run `python -m json.tool <file>` to find the syntax error |
| `KeyError: 'entry_parameters'` | Missing top-level component section | Empty sections are OK (`{"calculation": {}, ...}`); but the section key must be present |
| `KeyError: 'description'` or `'type'` | Param spec missing a required field | Every param needs `type` + `description`; calculation/usage need `range` + `default`; fixed needs `value` |

## Related skills

- **`parameter-patterns`** — architecture + ownership rules that this generator enforces. Read for the *why*; use this skill for the *how-to-call*. (Same skill tree, fetch via MCP `get_skill("parameter-patterns")` or read at `echolon/native/skills/echolon_api/parameter-patterns/`.)
- **`trading-api-core`** — describes how the generated `strategy_params.py` fits into runtime strategy execution.
- **`optuna_optimizer`** — consumes the generated `optuna_search_space` function to run the Optuna study.
- **`run_best_trial`** — consumes `DEFAULT_PARAMS` + `selected_robust_trial.json` to run a single backtest.

## Scope

`scope: universal` — no market or frequency restriction beyond the `frequency` arg's interday/intraday branch.
