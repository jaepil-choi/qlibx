"""
Trial Selection
===============

Intelligent trial selection for robust parameter choices.

MIGRATED FROM: modules/backtest/backtesting/select_best_trial.py
Changes:
- Config-driven instead of hardcoded paths
- Removed hardcoded strategy parameter dependencies
- Works with any strategy that provides DEFAULT_PARAMS and apply_shared_params

Why not just pick the best trial?
- Best trial may be overfit to training period
- Parameters may be unstable (small changes, big impact)
- Need to consider multiple performance aspects

TrialSelector analysis:
1. Performance clustering: Group similar-performing trials
2. Parameter stability: Prefer parameters in stable regions
3. Multi-objective: Balance return, risk, consistency

Selection criteria:
- Filter for drawdown survival (configurable threshold)
- Exclude zero-trade trials
- Cluster by parameter similarity
- Select from most robust cluster
"""

import pandas as pd
import numpy as np
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Callable, Mapping
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from echolon.backtest.schemas import SelectedTrialSchema

logger = logging.getLogger(__name__)


def convert_key_for_json(key: Any) -> str:
    """Convert a dictionary key to a JSON-serializable string."""
    if isinstance(key, tuple):
        return "_".join(str(k) for k in key)
    elif isinstance(key, (np.integer, np.int64, np.int32)):
        return str(int(key))
    elif isinstance(key, (np.floating, np.float64, np.float32)):
        return str(float(key))
    else:
        return str(key)


def convert_for_json(obj: Any) -> Any:
    """
    Recursively convert objects to JSON-serializable types.

    Handles numpy types, pandas types, and nested structures.
    Also converts non-string dictionary keys (including tuples) to strings.
    """
    if isinstance(obj, dict):
        return {convert_key_for_json(k): convert_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_for_json(v) for v in obj]
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    elif pd.isna(obj):
        return None
    else:
        return obj


class TrialSelector:
    """
    Analyzes Optuna trial performance data to select robust parameters.

    Uses clustering and stability analysis to find parameters that:
    - Perform well consistently
    - Are not overfit to specific periods
    - Lie in stable parameter regions

    Parameters
    ----------
    trial_data_path : str
        Path to the trial CSV file (from optuna study.trials_dataframe())
    output_dir : str
        Directory to save analysis results
    max_drawdown_threshold : float
        Maximum acceptable drawdown percentage (default 15.0)
    default_params : Dict[str, Any], optional
        Default parameters to fill in non-optimized params
    apply_shared_params_fn : Callable, optional
        Function to apply shared parameter constraints
    """

    def __init__(
        self,
        trial_data_path: str,
        output_dir: str,
        max_drawdown_threshold: float = 15.0,
        default_params: Optional[Dict[str, Any]] = None,
        apply_shared_params_fn: Optional[Callable[[Dict], Dict]] = None,
        param_classifications: Optional[Dict[str, Any]] = None,
        strategy_code_dir: Optional[Path] = None,
        search_space_fn: Optional[Callable[..., Dict[str, Any]]] = None,
        selection_score_fn: Optional[Callable[[pd.Series, Mapping[str, Any]], float]] = None,
        per_trial_returns: Optional[Mapping] = None,
    ):
        self.trial_data_path = trial_data_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True, parents=True)
        self.max_drawdown_threshold = max_drawdown_threshold
        self.default_params = default_params or {}
        self.apply_shared_params_fn = apply_shared_params_fn
        self.param_classifications = param_classifications
        # The strategy's generated optuna_search_space. When provided, select()
        # also emits resolved_params.json — the optimizer's exact nested
        # component dicts, replayed via FixedTrial — so consumers can bypass
        # the lossy strip-once flat-name mapping entirely.
        self.search_space_fn = search_space_fn
        # FLAG-1: optional caller-supplied scoring function.
        # Signature: (trial_row: pd.Series, context: Mapping[str, Any]) -> float
        # When None, the built-in risk_adjusted_return ranking is used (byte-identical default).
        # When provided, replaces idxmax() within the winning cluster only.
        # The OOS selection policy itself lives in the caller — this mechanism carries no policy.
        self.selection_score_fn = selection_score_fn
        # Context mapping passed as second arg to selection_score_fn.
        # Typically per_trial_returns from FLAG-2: {trial_number: {date: ret}}.
        self.per_trial_returns = per_trial_returns

        # selected_robust_trial.json goes to strategy_code_dir by default
        # (stays with strategy code for hypothesis testing)
        if strategy_code_dir is None:
            from echolon.config.paths_config import PathsConfig
            strategy_code_dir = PathsConfig.from_env().strategy_code_dir
        self.selected_trial_output_dir = Path(strategy_code_dir)
        self.selected_trial_output_dir.mkdir(exist_ok=True, parents=True)

        # Load and prepare data
        self.df = pd.read_csv(trial_data_path)
        self._prepare_data()

    def select(self) -> Optional[Dict[str, Any]]:
        """
        Run selection analysis and return the selected trial.

        Returns
        -------
        Optional[Dict[str, Any]]
            Selected trial info with parameters, or None if no suitable trial found
        """
        logger.info(f"[TRIAL_SELECTOR] Starting analysis | trials={len(self.df)}")

        robust_parameters = self._robust_parameter_identification()

        # Save full analysis record
        serializable_results = convert_for_json(robust_parameters)
        full_record_path = self.output_dir / 'full_trial_selection_record.json'
        with open(full_record_path, 'w') as f:
            json.dump(serializable_results, f, indent=2)
        logger.info(f"[TRIAL_SELECTOR] Saved full record to {full_record_path}")

        # Extract and save selected trial
        selected = robust_parameters.get('selected_robust_trial')
        if selected:
            # Validate against schema before saving (fail-fast)
            validated = SelectedTrialSchema.model_validate(selected)
            logger.info(f"[TRIAL_SELECTOR] Schema validated | trial={validated.trial_number}")

            # Save to platform_agnostic directory (stays with strategy code)
            selected_path = self.selected_trial_output_dir / 'selected_robust_trial.json'
            with open(selected_path, 'w') as f:
                json.dump(validated.model_dump(), f, indent=2)
            logger.info(f"[TRIAL_SELECTOR] Saved selected trial to {selected_path}")

            # Companion artifact: the RESOLVED effective vector (best-effort;
            # never blocks selection). See _export_resolved_params.
            self._export_resolved_params(validated.model_dump())

            metrics = validated.metrics
            logger.info(
                f"[TRIAL_SELECTOR] Selected trial {validated.trial_number} | "
                f"cluster={validated.cluster_id}, "
                f"sharpe={metrics.sharpe_ratio:.3f}, "
                f"return={metrics.annual_return:.2f}%, "
                f"max_dd={metrics.max_drawdown_pct:.2f}%"
            )
            return validated.model_dump()
        else:
            logger.warning("[TRIAL_SELECTOR] No robust trial found")
            return None

    def _export_resolved_params(self, selected: Dict[str, Any]) -> None:
        """Emit resolved_params.json next to selected_robust_trial.json (best-effort).

        The trial file's flat optuna names are mangled by the historical
        strip-once consumers (prefixed canonical names orphaned, bare names
        dropped, shared copies stale). Replaying the generated search space
        with FixedTrial reproduces the optimizer's exact nested dict; the
        sha256 provenance lets consumers detect a stale trial/resolved pair
        and fall back. Failure here is logged and skipped — selection itself
        must never be blocked by the companion export.

        Whenever a fresh export is NOT written (no search_space_fn, replay
        failure), any pre-existing resolved_params.json is removed: a trial
        save must never leave an OLDER companion pairing with the NEW trial
        file (the sha gate catches a params mismatch, but a same-params
        regeneration would not).
        """
        stale = self.selected_trial_output_dir / 'resolved_params.json'

        def _discard_stale() -> None:
            try:
                stale.unlink(missing_ok=True)
            except OSError:
                pass

        if self.search_space_fn is None:
            _discard_stale()
            return
        try:
            from echolon._internal.param_resolution import resolve_via_replay
            from echolon._internal.strategy_files import (
                save_resolved_params,
                trial_params_fingerprint,
            )

            flat = selected.get('params') or {}
            nested = resolve_via_replay(self.search_space_fn, flat)
            if nested is None:
                logger.warning(
                    "[TRIAL_SELECTOR] resolved_params export skipped (replay failed); "
                    "consumers will use the legacy flat-name mapping"
                )
                _discard_stale()
                return
            from datetime import datetime, timezone
            provenance = {
                'trial_number': selected.get('trial_number'),
                'trial_params_sha256': trial_params_fingerprint(flat),
                'generated_by': 'echolon TrialSelector',
                'created_utc': datetime.now(timezone.utc).isoformat(),
            }
            path = save_resolved_params(
                self.selected_trial_output_dir, nested, provenance=provenance
            )
            logger.info(f"[TRIAL_SELECTOR] Saved resolved params to {path}")
        except Exception as exc:
            logger.warning(
                f"[TRIAL_SELECTOR] resolved_params export failed (non-fatal): {exc}"
            )
            _discard_stale()

    def _prepare_data(self) -> None:
        """Prepare and clean the trial data."""
        # Rename performance columns for clarity
        self.df = self.df.rename(columns={
            'values_0': 'sharpe_ratio',
            'values_1': 'max_drawdown_pct',
            'values_2': 'annual_return'
        })

        # Extract parameter columns
        self.param_cols = [col for col in self.df.columns if col.startswith('params_')]
        self.performance_cols = ['sharpe_ratio', 'max_drawdown_pct', 'annual_return']

        # Handle missing values and infinite values
        self.df = self.df.replace([np.inf, -np.inf], np.nan)

        # Calculate additional metrics
        self.df['return_to_drawdown_ratio'] = (
            self.df['annual_return'] / np.abs(self.df['max_drawdown_pct'])
        )
        self.df['risk_adjusted_return'] = (
            self.df['annual_return'] / (1 + np.abs(self.df['max_drawdown_pct']) / 100)
        )

        # Create survival flag (trials that didn't hit drawdown threshold)
        self.df['survived_drawdown'] = (
            self.df['max_drawdown_pct'] > -self.max_drawdown_threshold
        )

        survival_rate = self.df['survived_drawdown'].mean()
        logger.info(f"[TRIAL_SELECTOR] Loaded {len(self.df)} trials, "
                   f"{survival_rate:.1%} survived drawdown filter")

    def _apply_parameter_sharing(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply shared parameter values from owner components.

        Uses the provided apply_shared_params_fn if available.
        """
        if self.apply_shared_params_fn is not None:
            return self.apply_shared_params_fn(params)
        return params

    def _robust_parameter_identification(self) -> Dict[str, Any]:
        """Identify robust parameter regions using clustering."""
        results = {}

        # Filter surviving trials and exclude zero-trade trials
        total_trials = len(self.df)
        drawdown_survivors = self.df['survived_drawdown'].sum()

        surviving_trials = self.df[
            (self.df['survived_drawdown']) &
            (self.df['sharpe_ratio'] != 0.0)  # Exclude zero-trade trials
        ].copy()

        trading_trials = len(surviving_trials)
        zero_trade_trials = drawdown_survivors - trading_trials

        logger.info(
            f"[TRIAL_SELECTOR] Filter | Total: {total_trials} | "
            f"Survived DD: {drawdown_survivors} | "
            f"Zero-trade: {zero_trade_trials} | "
            f"Trading: {trading_trials}"
        )

        if len(surviving_trials) < 10:
            results['warning'] = "Too few surviving trials for robust analysis"
            return results

        # Prepare parameter data for clustering
        param_data = surviving_trials[self.param_cols].copy()

        # Handle categorical parameters by encoding
        for col in param_data.columns:
            if param_data[col].dtype == 'object':
                param_data[col] = pd.Categorical(param_data[col]).codes

        # Standardize parameters
        scaler = StandardScaler()
        param_scaled = scaler.fit_transform(param_data.fillna(param_data.mean()))

        # Perform clustering
        n_clusters = min(5, len(surviving_trials) // 5)
        if n_clusters < 2:
            results['warning'] = "Too few trials for clustering"
            return results

        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        clusters = kmeans.fit_predict(param_scaled)
        surviving_trials['cluster'] = clusters

        # Create trial cluster assignments
        trial_cluster_assignments = []
        for _, row in surviving_trials.iterrows():
            trial_cluster_assignments.append({
                'trial_number': int(row['number']),
                'cluster_id': int(row['cluster']),
                'sharpe_ratio': row['sharpe_ratio'],
                'annual_return': row['annual_return'],
                'max_drawdown_pct': row['max_drawdown_pct'],
                'risk_adjusted_return': row['risk_adjusted_return']
            })

        # Sort by cluster and risk-adjusted return
        trial_cluster_assignments.sort(
            key=lambda x: (x['cluster_id'], -x['risk_adjusted_return'])
        )

        # Add ranking within each cluster
        cluster_rankings = []
        for cluster_id in range(n_clusters):
            cluster_trials = [
                t for t in trial_cluster_assignments
                if t['cluster_id'] == cluster_id
            ]
            for rank, trial in enumerate(cluster_trials, 1):
                cluster_rankings.append({
                    'trial_number': trial['trial_number'],
                    'cluster_id': trial['cluster_id'],
                    'rank_in_cluster': rank,
                    'total_in_cluster': len(cluster_trials),
                    'sharpe_ratio': trial['sharpe_ratio'],
                    'annual_return': trial['annual_return'],
                    'max_drawdown_pct': trial['max_drawdown_pct'],
                    'risk_adjusted_return': trial['risk_adjusted_return']
                })

        results['trial_cluster_assignments'] = trial_cluster_assignments
        results['trial_cluster_rankings'] = cluster_rankings

        # Analyze performance by cluster
        cluster_performance = surviving_trials.groupby('cluster')[
            self.performance_cols
        ].agg(['mean', 'std', 'count'])
        results['cluster_performance'] = cluster_performance.to_dict()

        # Find most robust cluster
        cluster_scores = {}
        for cluster_id in surviving_trials['cluster'].unique():
            cluster_data = surviving_trials[surviving_trials['cluster'] == cluster_id]
            if len(cluster_data) >= 3:
                mean_return = cluster_data['annual_return'].mean()
                mean_drawdown = cluster_data['max_drawdown_pct'].mean()
                mean_sharpe = cluster_data['sharpe_ratio'].mean()
                std_return = cluster_data['annual_return'].std()

                # Robustness score: Sharpe-centric
                score = mean_sharpe - (std_return * 0.1) - (abs(mean_drawdown) / 100)

                cluster_scores[cluster_id] = {
                    'robustness_score': score,
                    'mean_return': mean_return,
                    'mean_drawdown': mean_drawdown,
                    'mean_sharpe': mean_sharpe,
                    'std_return': std_return,
                    'trial_count': len(cluster_data)
                }

        results['cluster_robustness_scores'] = cluster_scores

        if not cluster_scores:
            results['warning'] = "No clusters with sufficient trials"
            return results

        # Identify most robust cluster
        best_cluster = max(
            cluster_scores.keys(),
            key=lambda x: cluster_scores[x]['robustness_score']
        )
        results['most_robust_cluster'] = int(best_cluster)

        # Get representative parameters from best cluster
        best_cluster_trials = surviving_trials[
            surviving_trials['cluster'] == best_cluster
        ]

        # Calculate median for numeric parameters
        numeric_param_cols = [
            col for col in self.param_cols
            if pd.api.types.is_numeric_dtype(best_cluster_trials[col])
        ]
        representative_params = best_cluster_trials[numeric_param_cols].median().to_dict()

        # Add non-numeric parameters (mode)
        non_numeric_param_cols = [
            col for col in self.param_cols
            if col not in numeric_param_cols
        ]
        for col in non_numeric_param_cols:
            mode_value = best_cluster_trials[col].mode()
            if not mode_value.empty:
                representative_params[col] = mode_value.iloc[0]

        results['robust_parameter_set'] = representative_params

        # Select best individual trial from most robust cluster
        if not best_cluster_trials.empty:
            if self.selection_score_fn is not None:
                # FLAG-1: caller-supplied scoring replaces built-in ranking.
                # Context (per_trial_returns or empty dict) is passed as second arg.
                context = self.per_trial_returns or {}
                scores = best_cluster_trials.apply(
                    lambda row: self.selection_score_fn(row, context), axis=1
                )
                best_trial_in_cluster = best_cluster_trials.loc[scores.idxmax()]
                selection_reason = 'Custom score from most robust cluster'
            else:
                best_trial_in_cluster = best_cluster_trials.loc[
                    best_cluster_trials['risk_adjusted_return'].idxmax()
                ]
                selection_reason = 'Highest risk-adjusted return from most robust cluster'

            trial_number = int(best_trial_in_cluster['number'])

            # Extract parameters, removing 'params_' prefix
            params = {
                k.replace('params_', ''): v
                for k, v in best_trial_in_cluster[self.param_cols].to_dict().items()
            }

            # Apply parameter sharing constraints
            params = self._apply_parameter_sharing(params)

            # Add default parameters that were not optimized
            for component_key, component_params in self.default_params.items():
                if component_key.endswith('_params') and isinstance(component_params, dict):
                    component_name = component_key.replace('_params', '')
                    for param_name, param_value in component_params.items():
                        full_key = f"{component_name}_{param_name}"
                        if full_key not in params and param_name != 'printlog':
                            params[full_key] = param_value
                elif not component_key.endswith('_params') and component_key not in params:
                    params[component_key] = component_params

            selected_trial_info = {
                'trial_number': trial_number,
                'selection_reason': selection_reason,
                'cluster_id': int(best_cluster),
                'cluster_robustness_score': cluster_scores[best_cluster]['robustness_score'],
                'parameter_stability_score': 1.0 / (1.0 + cluster_scores[best_cluster]['std_return']),
                'metrics': {
                    'sharpe_ratio': best_trial_in_cluster['sharpe_ratio'],
                    'annual_return': best_trial_in_cluster['annual_return'],
                    'max_drawdown_pct': best_trial_in_cluster['max_drawdown_pct'],
                },
                'params': params,
                'param_classifications': self.param_classifications,
            }
            results['selected_robust_trial'] = selected_trial_info

        return results

    def get_cluster_summary(self) -> pd.DataFrame:
        """
        Get a summary of all clusters with their performance metrics.

        Returns
        -------
        pd.DataFrame
            Summary table with cluster metrics
        """
        if 'cluster' not in self.df.columns:
            logger.warning("Clustering not performed yet. Run select() first.")
            return pd.DataFrame()

        surviving = self.df[
            (self.df['survived_drawdown']) &
            (self.df['sharpe_ratio'] != 0.0)
        ]

        summary = surviving.groupby('cluster').agg({
            'sharpe_ratio': ['mean', 'std', 'count'],
            'annual_return': ['mean', 'std'],
            'max_drawdown_pct': ['mean', 'std'],
            'risk_adjusted_return': ['mean', 'std']
        }).round(4)

        return summary

    def save_best_params(self, output_path: str) -> bool:
        """
        Save only the best parameters to a JSON file.

        Parameters
        ----------
        output_path : str
            Path to save the parameters

        Returns
        -------
        bool
            True if saved successfully
        """
        selected_path = self.selected_trial_output_dir / 'selected_robust_trial.json'
        if not selected_path.exists():
            logger.warning("No selected trial found. Run select() first.")
            return False

        with open(selected_path, 'r') as f:
            selected = json.load(f)

        params = selected.get('params', {})
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w') as f:
            json.dump(params, f, indent=2)

        logger.info(f"[TRIAL_SELECTOR] Saved best params to {output_file}")
        return True
