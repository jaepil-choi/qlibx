"""Acceptance tests for validate_component_logging.

AST scan verifying:
- VAL-003: the required ``log_<component>_output`` call is present in
  the component's required method body.
- VAL-006: the logged argument is the expected BaseModel type (no
  literal dict, no wrong-schema model).
- PRM-004: ``self.params.get('x')`` appears in the file (dict-access
  antipattern on the params container).

FP-insurance cases covered:
- ``out = EntrySignalOutput(...); self.log_entry_output(out)`` — local
  variable form (must pass).
- ``self.log_entry_output(EntrySignalOutput(...))`` — inline form (must pass).
- Calls on other attributes / instance methods not named
  ``log_<component>_output`` — must not trigger VAL-003.
"""
from pathlib import Path
import textwrap

from echolon.strategy.validators.component_logging import (
    validate_component_logging,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


def _canonical_entry_inline(tmp_path: Path) -> None:
    _write(tmp_path / "entry.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import EntrySignalOutput

        class entry_rule(BaseComponent):
            def generate_signal(self) -> EntrySignalOutput:
                out = EntrySignalOutput(
                    signal="HOLD", strength=0.0, type="hold",
                    entry_reason="x", intent=None, regime="unknown",
                )
                self.log_entry_output(out)
                return out
    ''')


def _canonical_exit(tmp_path: Path) -> None:
    _write(tmp_path / "exit.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import ExitSignalOutput

        class exit_rule(BaseComponent):
            def should_exit(self) -> ExitSignalOutput:
                out = ExitSignalOutput(
                    should_exit=False, exit_reason="x",
                    position_size=0.0, bars_since_entry=0, intent=None,
                )
                self.log_exit_output(out)
                return out
    ''')


def _canonical_risk(tmp_path: Path) -> None:
    _write(tmp_path / "risk.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import RiskOutput

        class risk_manager(BaseComponent):
            def can_trade(self) -> RiskOutput:
                out = RiskOutput(trading_allowed=True, risk_reason="x")
                self.log_risk_output(out)
                return out
    ''')


def _canonical_sizer(tmp_path: Path) -> None:
    _write(tmp_path / "sizer.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import EntrySignalOutput, SizerOutput

        class position_sizer(BaseComponent):
            def calculate_size(self, entry_signal: EntrySignalOutput) -> SizerOutput:
                out = SizerOutput(
                    calculated_size=1, signal_direction="HOLD",
                    sizing_reason="x", raw_size=1.0,
                )
                self.log_sizer_output(out)
                return out
    ''')


def _canonical_all_local_var(tmp_path: Path) -> None:
    _canonical_entry_inline(tmp_path)
    _canonical_exit(tmp_path)
    _canonical_risk(tmp_path)
    _canonical_sizer(tmp_path)


def test_canonical_local_variable_form_no_findings(tmp_path: Path):
    _canonical_all_local_var(tmp_path)
    report = validate_component_logging(strategy_dir=tmp_path)
    assert not report.any_errors, report.findings


def test_canonical_inline_form_no_findings(tmp_path: Path):
    """Entry using the inline form: self.log_entry_output(EntrySignalOutput(...))."""
    _write(tmp_path / "entry.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import EntrySignalOutput

        class entry_rule(BaseComponent):
            def generate_signal(self) -> EntrySignalOutput:
                self.log_entry_output(EntrySignalOutput(
                    signal="HOLD", strength=0.0, type="hold",
                    entry_reason="x", intent=None, regime="unknown",
                ))
                return EntrySignalOutput(
                    signal="HOLD", strength=0.0, type="hold",
                    entry_reason="x", intent=None, regime="unknown",
                )
    ''')
    _canonical_exit(tmp_path)
    _canonical_risk(tmp_path)
    _canonical_sizer(tmp_path)

    report = validate_component_logging(strategy_dir=tmp_path)
    assert not report.any_errors, report.findings


def test_missing_log_call_surfaces_VAL_003(tmp_path: Path):
    # entry.py generates a signal but doesn't log.
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
    _canonical_exit(tmp_path)
    _canonical_risk(tmp_path)
    _canonical_sizer(tmp_path)

    report = validate_component_logging(strategy_dir=tmp_path)
    codes = [f.code for f in report.findings]
    assert "VAL-003" in codes
    f = next(f for f in report.findings if f.code == "VAL-003")
    assert f.context.get("missing_call") == "log_entry_output"


def test_logged_dict_surfaces_VAL_006(tmp_path: Path):
    """Agent calls self.log_entry_output({...}) with a literal dict."""
    _write(tmp_path / "entry.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import EntrySignalOutput

        class entry_rule(BaseComponent):
            def generate_signal(self) -> EntrySignalOutput:
                self.log_entry_output({"signal": "HOLD", "strength": 0.0})
                return EntrySignalOutput(
                    signal="HOLD", strength=0.0, type="hold",
                    entry_reason="x", intent=None, regime="unknown",
                )
    ''')
    _canonical_exit(tmp_path)
    _canonical_risk(tmp_path)
    _canonical_sizer(tmp_path)

    report = validate_component_logging(strategy_dir=tmp_path)
    codes = [f.code for f in report.findings]
    assert "VAL-006" in codes
    f = next(f for f in report.findings if f.code == "VAL-006")
    assert f.context.get("expected_return") == "EntrySignalOutput"
    # Describe what was actually passed.
    assert "dict" in str(f.context.get("actual_annotation", ""))


def test_logged_wrong_schema_type_surfaces_VAL_006(tmp_path: Path):
    """Agent mixes up schemas: passes an ExitSignalOutput to log_entry_output."""
    _write(tmp_path / "entry.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import EntrySignalOutput, ExitSignalOutput

        class entry_rule(BaseComponent):
            def generate_signal(self) -> EntrySignalOutput:
                wrong = ExitSignalOutput(
                    should_exit=False, exit_reason="x",
                    position_size=0.0, bars_since_entry=0, intent=None,
                )
                self.log_entry_output(wrong)
                return EntrySignalOutput(
                    signal="HOLD", strength=0.0, type="hold",
                    entry_reason="x", intent=None, regime="unknown",
                )
    ''')
    _canonical_exit(tmp_path)
    _canonical_risk(tmp_path)
    _canonical_sizer(tmp_path)

    report = validate_component_logging(strategy_dir=tmp_path)
    codes = [f.code for f in report.findings]
    assert "VAL-006" in codes


def test_params_dict_get_surfaces_PRM_004(tmp_path: Path):
    """self.params.get('x') is a PRM-004 antipattern."""
    _write(tmp_path / "entry.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import EntrySignalOutput

        class entry_rule(BaseComponent):
            def generate_signal(self) -> EntrySignalOutput:
                threshold = self.params.get("cci_threshold", 100.0)
                out = EntrySignalOutput(
                    signal="HOLD", strength=0.0, type="hold",
                    entry_reason="x", intent=None, regime="unknown",
                )
                self.log_entry_output(out)
                return out
    ''')
    _canonical_exit(tmp_path)
    _canonical_risk(tmp_path)
    _canonical_sizer(tmp_path)

    report = validate_component_logging(strategy_dir=tmp_path)
    codes = [f.code for f in report.findings]
    assert "PRM-004" in codes
    f = next(f for f in report.findings if f.code == "PRM-004")
    assert "cci_threshold" in f.context.get("call", "") or "params.get" in f.context.get("call", "")


def test_fp_insurance_other_method_calls_must_not_raise(tmp_path: Path):
    """The validator only checks for log_<component>_output and
    self.params.get. Other instance-method calls (self.get_indicator,
    self.get_market_regime, self.entry, custom helpers) must NOT
    trigger any finding."""
    _write(tmp_path / "entry.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import EntrySignalOutput

        class entry_rule(BaseComponent):
            def generate_signal(self) -> EntrySignalOutput:
                cci = self.get_indicator('cci_14')
                regime = self.get_market_regime()
                self.some_strategy_local_helper(cci, regime)
                out = EntrySignalOutput(
                    signal="HOLD", strength=0.0, type="hold",
                    entry_reason="x", intent=None, regime=regime,
                )
                self.log_entry_output(out)
                return out

            def some_strategy_local_helper(self, *args): pass
    ''')
    _canonical_exit(tmp_path)
    _canonical_risk(tmp_path)
    _canonical_sizer(tmp_path)

    report = validate_component_logging(strategy_dir=tmp_path)
    assert not report.any_errors, (
        f"FP insurance violated — only log_<component>_output and "
        f"params.get should be flagged. Got: {report.findings}"
    )


def test_missing_file_is_silently_skipped(tmp_path: Path):
    """Missing files are preflight's concern (STR-001). This validator
    skips them."""
    _canonical_entry_inline(tmp_path)
    # No exit/risk/sizer.

    report = validate_component_logging(strategy_dir=tmp_path)
    # Only entry present and valid — no findings from absent files.
    assert all("exit.py" not in str(f.context) for f in report.findings)
    assert all("risk.py" not in str(f.context) for f in report.findings)
