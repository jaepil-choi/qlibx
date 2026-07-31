"""Acceptance tests for validate_parameter_access.

Highest FP risk of the 5 validators. Ships in warning-only mode by
default (callers decide whether to block on findings). The 4 FP-insurance
test cases below are the minimum bar — any regression that starts raising
on these patterns means the allowlist broke.
"""
from pathlib import Path
import textwrap

from echolon.strategy.validators.parameter_access import (
    validate_parameter_access,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


def _canonical_skeleton(tmp_path: Path) -> None:
    """Base skeleton — no violations. Individual tests mutate entry.py."""
    _write(tmp_path / "exit.py", "class exit_rule: pass\n")
    _write(tmp_path / "risk.py", "class risk_manager: pass\n")
    _write(tmp_path / "sizer.py", "class position_sizer: pass\n")


# ============================================================================
# PRM-003 violations — hardcoded numeric thresholds
# ============================================================================


def test_hardcoded_numeric_threshold_in_if_surfaces_PRM_003(tmp_path: Path):
    _canonical_skeleton(tmp_path)
    _write(tmp_path / "entry.py", '''
        class entry_rule:
            def generate_signal(self):
                cci = self.get_indicator('cci_14')
                if cci > 30:   # <-- PRM-003: hardcoded threshold 30
                    return "LONG"
                return "HOLD"
    ''')
    report = validate_parameter_access(strategy_dir=tmp_path)
    codes = [f.code for f in report.findings]
    assert "PRM-003" in codes


def test_hardcoded_float_threshold_in_elif_surfaces_PRM_003(tmp_path: Path):
    _canonical_skeleton(tmp_path)
    _write(tmp_path / "entry.py", '''
        class entry_rule:
            def generate_signal(self):
                obv = self.get_indicator('obv')
                if obv > self.obv_threshold:
                    return "SHORT"
                elif obv < 1000.5:   # <-- PRM-003: hardcoded float 1000.5
                    return "HOLD"
                return "HOLD"
    ''')
    codes = [f.code for f in validate_parameter_access(strategy_dir=tmp_path).findings]
    assert "PRM-003" in codes


def test_params_dict_get_surfaces_PRM_004(tmp_path: Path):
    _canonical_skeleton(tmp_path)
    _write(tmp_path / "entry.py", '''
        class entry_rule:
            def generate_signal(self):
                threshold = self.params.get("cci_threshold", 100.0)
                cci = self.get_indicator('cci_14')
                if cci > threshold:
                    return "LONG"
                return "HOLD"
    ''')
    codes = [f.code for f in validate_parameter_access(strategy_dir=tmp_path).findings]
    assert "PRM-004" in codes


# ============================================================================
# FP INSURANCE — the binding tests. If any of these fail, the validator
# has regressed to blocking legitimate code. Fix the validator, not the test.
# ============================================================================


def test_fp_insurance_1_loop_counter_must_not_raise(tmp_path: Path):
    """Loop counters in ``range(N)`` are not threshold literals."""
    _canonical_skeleton(tmp_path)
    _write(tmp_path / "entry.py", '''
        class entry_rule:
            def generate_signal(self):
                history = []
                for i in range(10):
                    history.append(i)
                for j in range(1, 20, 2):
                    pass
                return "HOLD"
    ''')
    report = validate_parameter_access(strategy_dir=tmp_path)
    assert not any(f.code == "PRM-003" for f in report.findings), (
        f"FP-insurance-1 failed: range() args must not flag PRM-003. "
        f"Got: {report.findings}"
    )


def test_fp_insurance_2_none_comparison_must_not_raise(tmp_path: Path):
    """``is None`` / ``is not None`` are canonical Python, never a
    parameter-access smell."""
    _canonical_skeleton(tmp_path)
    _write(tmp_path / "entry.py", '''
        class entry_rule:
            def generate_signal(self):
                cached = self._maybe_cached_value
                if cached is None:
                    return "HOLD"
                if cached is not None:
                    return "LONG"
                return "HOLD"
    ''')
    report = validate_parameter_access(strategy_dir=tmp_path)
    assert not report.any_errors, (
        f"FP-insurance-2 failed: None comparisons must not flag. "
        f"Got: {report.findings}"
    )


def test_fp_insurance_3_index_slicing_must_not_raise(tmp_path: Path):
    """Numeric literals in subscript / index positions are structural
    access, not threshold literals."""
    _canonical_skeleton(tmp_path)
    _write(tmp_path / "entry.py", '''
        class entry_rule:
            def generate_signal(self):
                bars = self.get_indicator('close_history')
                last = bars[-1]
                first_five = bars[:5]
                window = bars[-20:-1]
                last_bar_index = len(bars) - 1
                return "HOLD"
    ''')
    report = validate_parameter_access(strategy_dir=tmp_path)
    assert not report.any_errors, (
        f"FP-insurance-3 failed: index slicing must not flag. "
        f"Got: {report.findings}"
    )


def test_fp_insurance_4_kwargs_must_not_raise(tmp_path: Path):
    """Numeric literals in keyword arguments are library kwargs, not
    trading thresholds."""
    _canonical_skeleton(tmp_path)
    _write(tmp_path / "entry.py", '''
        class entry_rule:
            def generate_signal(self):
                result = some_helper(timeout=30, retries=3, buffer_size=1024)
                arr = list(range(10))
                return "HOLD"

        def some_helper(**kwargs):
            return None
    ''')
    report = validate_parameter_access(strategy_dir=tmp_path)
    assert not report.any_errors, (
        f"FP-insurance-4 failed: kwargs must not flag. "
        f"Got: {report.findings}"
    )


def test_fp_insurance_5_small_integer_arithmetic_must_not_raise(tmp_path: Path):
    """``-1``, ``+1``, ``0`` in arithmetic / indexing are not threshold
    literals."""
    _canonical_skeleton(tmp_path)
    _write(tmp_path / "entry.py", '''
        class entry_rule:
            def generate_signal(self):
                count = 0
                count = count + 1
                last_idx = len(self.history) - 1
                return "HOLD"
    ''')
    report = validate_parameter_access(strategy_dir=tmp_path)
    assert not report.any_errors, (
        f"FP-insurance-5 failed: small-int arithmetic must not flag. "
        f"Got: {report.findings}"
    )


def test_fp_insurance_6_string_enum_comparison_must_not_raise(tmp_path: Path):
    """``signal == "LONG"``, ``regime == "trending_up"`` — framework-
    defined enum values. Do not flag string literals in comparisons."""
    _canonical_skeleton(tmp_path)
    _write(tmp_path / "entry.py", '''
        class entry_rule:
            def generate_signal(self):
                regime = self.get_market_regime()
                if regime == "trending_up":
                    return "LONG"
                elif regime == "volatile":
                    return "SHORT"
                elif regime == "some_custom_regime_name":
                    return "HOLD"
                return "HOLD"
    ''')
    report = validate_parameter_access(strategy_dir=tmp_path)
    assert not report.any_errors, (
        f"FP-insurance-6 failed: string literal in enum-style comparison "
        f"must not flag. Got: {report.findings}"
    )


def test_fp_insurance_7_default_argument_must_not_raise(tmp_path: Path):
    """Default argument values in function defs are configuration
    surface, not in-body thresholds."""
    _canonical_skeleton(tmp_path)
    _write(tmp_path / "entry.py", '''
        class entry_rule:
            def _helper(self, multiplier=2, offset=0):
                return multiplier + offset
            def generate_signal(self):
                return "HOLD"
    ''')
    report = validate_parameter_access(strategy_dir=tmp_path)
    assert not report.any_errors, (
        f"FP-insurance-7 failed: default args must not flag. "
        f"Got: {report.findings}"
    )


def test_fp_insurance_8_float_sentinel_must_not_raise(tmp_path: Path):
    """Float sentinels ``-1.0``, ``0.0``, ``1.0`` are structural constants
    (minimum-lot gates, zero-check sentinels). Not tunable thresholds.
    Canary (commit 93f7aad) found 34/34 baselines hit this via
    ``if computed_raw_size >= 1.0:`` in sizer.py."""
    _canonical_skeleton(tmp_path)
    _write(tmp_path / "sizer.py", '''
        class position_sizer:
            def calculate_size(self, entry_signal):
                computed_raw_size = self.raw_size_estimate()
                if computed_raw_size >= 1.0:
                    return int(computed_raw_size)
                if computed_raw_size > 0.0:
                    return 1
                return 0
    ''')
    report = validate_parameter_access(strategy_dir=tmp_path)
    assert not report.any_errors, (
        f"FP-insurance-8 failed: float sentinels must not flag. "
        f"Got: {report.findings}"
    )


# ============================================================================
# Integration / negative tests
# ============================================================================


def test_canonical_parameter_access_no_findings(tmp_path: Path):
    """The correct pattern — all thresholds come from self.<attr>."""
    _canonical_skeleton(tmp_path)
    _write(tmp_path / "entry.py", '''
        class entry_rule:
            def generate_signal(self):
                cci = self.get_indicator('cci_14')
                if cci > self.cci_threshold:
                    return "LONG"
                if cci < self.cci_lower:
                    return "SHORT"
                return "HOLD"
    ''')
    report = validate_parameter_access(strategy_dir=tmp_path)
    assert not report.any_errors, report.findings


def test_missing_file_silent_skip(tmp_path: Path):
    """No entry.py — silent, per preflight responsibility split."""
    _canonical_skeleton(tmp_path)
    (tmp_path / "exit.py").unlink()
    report = validate_parameter_access(strategy_dir=tmp_path)
    assert not any("exit.py" in str(f.context) for f in report.findings)
