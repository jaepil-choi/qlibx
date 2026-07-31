"""v0.2.x signature assertions for run_indicator_calculation."""
import inspect

from echolon.indicators.run import run_indicator_calculation


def test_required_params_are_ctx_output_dir_indicator_list():
    """`paths` joined the required set in v0.3 (no more from_env() fallback —
    every caller threads a PathsConfig built once at program startup)."""
    sig = inspect.signature(run_indicator_calculation)
    required = [
        name for name, p in sig.parameters.items()
        if p.default is inspect.Parameter.empty and p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY,
        )
    ]
    assert set(required) == {"ctx", "output_dir", "indicator_list", "paths"}


def test_removed_params_are_gone():
    sig = inspect.signature(run_indicator_calculation)
    for removed in ("selected_only", "mode", "optimize_regime",
                    "backtest_start_year", "indicator_config"):
        assert removed not in sig.parameters, f"'{removed}' should be removed"


def test_retained_params_present():
    sig = inspect.signature(run_indicator_calculation)
    for name in ("use_parallel", "trading_dates", "regime_params",
                 "start_date", "end_date"):
        assert name in sig.parameters, f"'{name}' should remain"
