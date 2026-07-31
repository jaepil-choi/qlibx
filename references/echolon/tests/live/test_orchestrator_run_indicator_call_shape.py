"""Phase A7 — deploy orchestrators call run_indicator_calculation with the real signature.

No unit tests existed previously; the old kwargs (indicator_config=, selected_only=,
mode=, optimize_regime=) would have raised TypeError at runtime. These tests
assert the call shape symbolically by grep'ing the source.
"""
import inspect
from pathlib import Path

from echolon.indicators.run import run_indicator_calculation


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _src(rel_path: str) -> str:
    return (_REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_run_indicator_calculation_signature_has_indicator_list():
    """The signature we rely on. Reject surprise renames."""
    sig = inspect.signature(run_indicator_calculation)
    assert "indicator_list" in sig.parameters
    assert "ctx" in sig.parameters
    assert "output_dir" in sig.parameters


def test_portfolio_does_not_use_deprecated_kwargs():
    # Phase 0 implementation lives in phase0_pipeline.py post-2026-05-08 refactor;
    # also assert nothing came back into portfolio.py.
    portfolio_src = _src("echolon/live/orchestrator/portfolio.py")
    pipeline_src = _src("echolon/live/orchestrator/phase0_pipeline.py")
    # These kwargs do NOT exist on run_indicator_calculation — must not appear as kwargs.
    for bad in ("selected_only=", "mode=", "optimize_regime=", "indicator_config="):
        assert bad not in portfolio_src, f"portfolio.py still references deprecated kwarg {bad!r}"
        assert bad not in pipeline_src, f"phase0_pipeline.py still references deprecated kwarg {bad!r}"
    # Must pass the actual kwarg (uses merged_indicator_list from the grouping step)
    assert "indicator_list=merged_indicator_list" in pipeline_src
