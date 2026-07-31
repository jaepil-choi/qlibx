"""Acceptance tests for validate_component_integration.

Checks:
- STR-002: component module imports cleanly via StrategyLoader.
- PRM-002: strategy_params.DEFAULT_PARAMS has all 4 top-level component keys,
  and each value is a dict.
- VAL-005: each component's required method has the expected positional
  signature (post-self).

FP-insurance (extra sub-keys in entry_params / exit_params etc must NOT
raise) is locked by ``test_fp_insurance_extra_subkeys_must_not_raise``.
"""
from pathlib import Path
import textwrap

import pytest

from echolon.strategy.validators.component_integration import (
    validate_component_integration,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


def _canonical_strategy(tmp_path: Path) -> None:
    """Minimal scaffold-style strategy that passes all 3 checks."""
    _write(tmp_path / "entry.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import EntrySignalOutput

        class entry_rule(BaseComponent):
            def generate_signal(self) -> EntrySignalOutput:
                return EntrySignalOutput(
                    signal="HOLD", strength=0.0, type="hold",
                    entry_reason="x", intent=None, regime="unknown",
                )
    ''')
    _write(tmp_path / "exit.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import ExitSignalOutput

        class exit_rule(BaseComponent):
            def should_exit(self) -> ExitSignalOutput:
                return ExitSignalOutput(
                    should_exit=False, exit_reason="x",
                    position_size=0.0, bars_since_entry=0, intent=None,
                )
    ''')
    _write(tmp_path / "risk.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import RiskOutput

        class risk_manager(BaseComponent):
            def can_trade(self) -> RiskOutput:
                return RiskOutput(trading_allowed=True, risk_reason="x")
    ''')
    _write(tmp_path / "sizer.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import EntrySignalOutput, SizerOutput

        class position_sizer(BaseComponent):
            def calculate_size(self, entry_signal: EntrySignalOutput) -> SizerOutput:
                return SizerOutput(
                    calculated_size=1, signal_direction="HOLD",
                    sizing_reason="x", raw_size=1.0,
                )
    ''')
    _write(tmp_path / "strategy_params.py", '''
        DEFAULT_PARAMS = {
            "entry_params":  {"printlog": False},
            "exit_params":   {"printlog": False},
            "risk_params":   {"printlog": False},
            "sizer_params":  {"printlog": False},
        }
    ''')


def test_canonical_strategy_no_findings(tmp_path: Path):
    _canonical_strategy(tmp_path)
    report = validate_component_integration(strategy_dir=tmp_path)
    assert not report.any_errors, report.findings


def test_import_error_surfaces_STR_002(tmp_path: Path):
    _canonical_strategy(tmp_path)
    # Corrupt entry.py with an unresolvable import.
    _write(tmp_path / "entry.py", '''
        from nonexistent_package_xyz_12345 import Something  # unimportable

        class entry_rule:
            def generate_signal(self): pass
    ''')

    report = validate_component_integration(strategy_dir=tmp_path)
    codes = [f.code for f in report.findings]
    assert "STR-002" in codes
    # Context includes the failing file + exception repr.
    f = next(f for f in report.findings if f.code == "STR-002")
    assert "entry.py" in f.context.get("file", "")


def test_missing_default_params_top_level_key_surfaces_PRM_002(tmp_path: Path):
    _canonical_strategy(tmp_path)
    _write(tmp_path / "strategy_params.py", '''
        DEFAULT_PARAMS = {
            "entry_params":  {"printlog": False},
            "exit_params":   {"printlog": False},
            "risk_params":   {"printlog": False},
            # sizer_params deliberately missing
        }
    ''')

    report = validate_component_integration(strategy_dir=tmp_path)
    codes = [f.code for f in report.findings]
    assert "PRM-002" in codes
    f = next(f for f in report.findings if f.code == "PRM-002")
    assert "sizer_params" in f.context.get("missing_keys", [])


def test_default_params_top_level_not_a_dict_surfaces_PRM_002(tmp_path: Path):
    _canonical_strategy(tmp_path)
    _write(tmp_path / "strategy_params.py", '''
        DEFAULT_PARAMS = {
            "entry_params":  {"printlog": False},
            "exit_params":   "this should be a dict, not a string",
            "risk_params":   {"printlog": False},
            "sizer_params":  {"printlog": False},
        }
    ''')

    report = validate_component_integration(strategy_dir=tmp_path)
    codes = [f.code for f in report.findings]
    assert "PRM-002" in codes


def test_method_signature_mismatch_surfaces_VAL_005(tmp_path: Path):
    _canonical_strategy(tmp_path)
    # sizer: remove the required positional arg entirely (arity drops from 1 to 0).
    _write(tmp_path / "sizer.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import SizerOutput

        class position_sizer(BaseComponent):
            def calculate_size(self) -> SizerOutput:  # missing required positional arg
                return SizerOutput(
                    calculated_size=1, signal_direction="HOLD",
                    sizing_reason="x", raw_size=1.0,
                )
    ''')

    report = validate_component_integration(strategy_dir=tmp_path)
    codes = [f.code for f in report.findings]
    assert "VAL-005" in codes
    f = next(f for f in report.findings if f.code == "VAL-005")
    assert f.context.get("method") == "calculate_size"
    # Expected arity is 1; actual arity is 0.
    assert "1" in (f.context.get("expected") or "")
    assert "0" in f.message


def test_sizer_signature_with_different_arg_name_does_not_raise(tmp_path: Path):
    """The framework calls calculate_size positionally — arg name is the
    author's choice. ``signal_data`` is just as valid as ``entry_signal``.
    FP insurance against the name-matching over-fit that was fixed by
    moving to arity-only checking."""
    _canonical_strategy(tmp_path)
    _write(tmp_path / "sizer.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import EntrySignalOutput, SizerOutput

        class position_sizer(BaseComponent):
            def calculate_size(self, signal_data: EntrySignalOutput) -> SizerOutput:
                return SizerOutput(
                    calculated_size=1, signal_direction="HOLD",
                    sizing_reason="x", raw_size=1.0,
                )
    ''')

    report = validate_component_integration(strategy_dir=tmp_path)
    codes = [f.code for f in report.findings]
    assert "VAL-005" not in codes, (
        f"FP: arg name difference must not flag — only arity matters. "
        f"Got: {report.findings}"
    )


def test_fp_insurance_extra_subkeys_must_not_raise(tmp_path: Path):
    """FP insurance: the framework allows extra keys inside each
    component's param sub-dict. Adding, say, cci_period + obv_threshold
    under entry_params is the NORMAL state of a real strategy — the
    validator must NOT raise on that."""
    _canonical_strategy(tmp_path)
    _write(tmp_path / "strategy_params.py", '''
        DEFAULT_PARAMS = {
            "entry_params": {
                "printlog": False,
                "cci_period": 14,
                "cci_threshold": 100.0,
                "obv_threshold": 0,
                "some_totally_undeclared_extra": "ok",
            },
            "exit_params":  {"printlog": False, "atr_period": 14},
            "risk_params":  {"printlog": False, "max_dd_pct": 6.5},
            "sizer_params": {"printlog": False, "risk_pct": 0.01},
        }
    ''')

    report = validate_component_integration(strategy_dir=tmp_path)
    assert not report.any_errors, (
        f"FP insurance violated — extra sub-keys are legitimate. "
        f"Got findings: {report.findings}"
    )


def test_missing_file_is_silently_skipped(tmp_path: Path):
    """Preflight STR-001 handles file presence. This validator skips
    absent files without duplicate findings."""
    # Only write entry.py + strategy_params.py
    _canonical_strategy(tmp_path)
    (tmp_path / "exit.py").unlink()
    (tmp_path / "risk.py").unlink()
    (tmp_path / "sizer.py").unlink()

    report = validate_component_integration(strategy_dir=tmp_path)
    # entry + strategy_params checks pass; missing files are silent.
    # No STR-001-style findings from this validator.
    assert all(f.code != "STR-001" for f in report.findings), report.findings


def test_missing_strategy_params_file_is_silent(tmp_path: Path):
    """Same reasoning — preflight handles missing files."""
    _canonical_strategy(tmp_path)
    (tmp_path / "strategy_params.py").unlink()

    report = validate_component_integration(strategy_dir=tmp_path)
    # Component-signature checks still run; params checks skip.
    codes_present = [f.code for f in report.findings]
    assert "PRM-002" not in codes_present, (
        f"Missing strategy_params.py should be silent (preflight territory), "
        f"not surfaced as PRM-002. Got: {report.findings}"
    )
