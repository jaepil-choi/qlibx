---
name: trial_selector
description: Clusters Optuna trial outcomes with KMeans on standardized parameters, picks the most robust cluster by Sharpe-centric score, and writes selected_robust_trial.json to the strategy code directory for run_best_trial to pick up.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.backtest.optimization.select_best_trial.TrialSelector

## Purpose

`TrialSelector` reads the CSV dumped by `OptunaOptimizer.save_study_results()` (columns: `number`, `values_0..values_2`, `params_*`) and picks a *robust* trial rather than the Optuna-best one. It filters out trials that breached a drawdown threshold or have zero trades, KMeans-clusters the survivors on their (standardized) parameter vectors, scores each cluster by `mean_sharpe - 0.1·std_return - |mean_drawdown|/100`, and then within the winning cluster picks the single trial with the highest `risk_adjusted_return`. Output goes to two places: `{output_dir}/full_trial_selection_record.json` (all cluster analysis) and `{strategy_code_dir}/selected_robust_trial.json` (the single trial, validated against `SelectedTrialSchema`, that `run_best_trial` will replay).

## Interface

```python
from pathlib import Path
from echolon.backtest.optimization.select_best_trial import TrialSelector
from my_strategy.strategy_params import (
    DEFAULT_PARAMS, apply_shared_params, framework,
)

# 1. Standard wiring — matches WFARunner's usage.
selector = TrialSelector(
    trial_data_path="/path/to/optimization_trials.csv",
    output_dir="/path/to/wfa/window_1",
    max_drawdown_threshold=15.0,
    default_params=DEFAULT_PARAMS,
    apply_shared_params_fn=apply_shared_params,
    param_classifications=framework.get_param_classifications(),
)

selected = selector.select()
# -> {'trial_number': 42, 'cluster_id': 2, 'metrics': {...},
#     'params': {...}, 'param_classifications': {...}}
# or None if no trial met the filters.

# 2. Override where selected_robust_trial.json is written (default:
#    PathsConfig.from_env().strategy_code_dir).
selector = TrialSelector(..., strategy_code_dir=Path("/tmp/slot_3"))

# 3. Post-selection helpers.
summary = selector.get_cluster_summary()        # cluster performance DataFrame
selector.save_best_params("/tmp/just_params.json")
```

## When to use

- Directly after an Optuna optimization completes, before calling `run_best_trial(ctx)` — the latter expects `selected_robust_trial.json` under `PathsConfig.strategy_code_dir`.
- Inside `WFARunner.run()` once per window. WFA passes the strategy's `DEFAULT_PARAMS`, `apply_shared_params`, and `framework.get_param_classifications()` so that (a) non-optimized params get filled in from defaults and (b) shared parameters (e.g. same RSI period reused by entry+exit) stay consistent in the final JSON.
- Do *not* rely on Optuna's `study.best_trial` for production parameter selection — it is often overfit, unstable, or comes from a sparse parameter region. `TrialSelector` exists specifically to solve that.
- Do *not* skip `_apply_parameter_sharing` when your strategy has shared parameter groups. If `apply_shared_params_fn` is `None`, parameters from the owner component will not propagate to dependents and the replayed backtest will diverge from the Optuna trial.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `__init__(trial_data_path, output_dir, max_drawdown_threshold=15.0, default_params=None, apply_shared_params_fn=None, param_classifications=None, strategy_code_dir=None)` | see above | — | Loads the CSV via `pd.read_csv`, runs `_prepare_data` (renames `values_0→sharpe_ratio`, `values_1→max_drawdown_pct`, `values_2→annual_return`; computes `return_to_drawdown_ratio`, `risk_adjusted_return`, `survived_drawdown`). |
| `select()` | — | `Optional[Dict[str, Any]]` | Runs `_robust_parameter_identification`, validates the result against `SelectedTrialSchema`, writes both JSONs, returns the selected trial as a dict. Returns `None` if too few survivors (<10) or no clusters have ≥3 trials. |
| `get_cluster_summary()` | — | `pd.DataFrame` | Per-cluster agg of `sharpe_ratio`, `annual_return`, `max_drawdown_pct`, `risk_adjusted_return` (mean+std+count). Returns empty if `select()` has not been called. |
| `save_best_params(output_path)` | str | `bool` | Reads `selected_robust_trial.json`, writes just the `params` dict to `output_path`. Returns False if no selected trial exists. |
| Helpers | `convert_key_for_json`, `convert_for_json` | — | Recursively coerce numpy/pandas types to JSON-safe values. Keys converted to strings (tuples become `"a_b"`). |

Internal steps (`_robust_parameter_identification`):
1. Filter: `survived_drawdown & sharpe_ratio != 0.0`. Logs total / survived / zero-trade / trading counts.
2. Early-exit: `< 10` survivors or `n_clusters < 2`.
3. Encode non-numeric params via `pd.Categorical`, standardize via `StandardScaler`, fit `KMeans(n_clusters=min(5, len/5), random_state=42, n_init=10)`.
4. Score each cluster (≥3 trials) by `mean_sharpe - 0.1·std_return - |mean_drawdown|/100`.
5. Pick cluster with highest score. Compute median for numeric params, mode for non-numeric.
6. Pick best individual trial within that cluster by `idxmax(risk_adjusted_return)`.
7. Remove `params_` prefix, apply `apply_shared_params_fn`, fill missing keys from `default_params`.

## Common errors

- **`FileNotFoundError: [Errno 2] ... optimization_trials.csv`** — the Optuna study never wrote trials. `OptunaOptimizer.save_study_results(..., save_trials_csv=True)` was not called, or the optimization failed before completion. No Echolon code.
- **`pydantic.ValidationError`** from `SelectedTrialSchema.model_validate(selected)` — the internal dict shape drifted from the schema. Common cause: a strategy's `apply_shared_params_fn` returns unexpected keys. Inspect the error and align the schema in `echolon.backtest.schemas`.
- **Warning-only "No robust trial found"** — less than 10 surviving trials, fewer than 2 clusters possible, or no cluster with ≥3 trials. Returns `None`; `full_trial_selection_record.json` is written with a `warning` field. Increase `n_trials`, loosen `max_drawdown_threshold`, or widen the search space.
- **Silent parameter mismatch after replay** — occurs when `apply_shared_params_fn=None` but the strategy has shared groups. The replayed backtest will deviate from the Optuna trial. Always pass the strategy's own `apply_shared_params`.

## See also

- `optuna_optimizer` skill — writes the `optimization_trials.csv` consumed here.
- `run_best_trial` skill — reads the `selected_robust_trial.json` written here.
- `wfa_runner` skill — the standard orchestrator that pairs `OptunaOptimizer`, `TrialSelector`, and `run_best_trial` per window.
- echolon docs: `echolon/backtest/schemas.py` (SelectedTrialSchema), `the component_guide skill`.
