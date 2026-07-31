"""Acceptance tests for validate_component_signatures.

Rules locked by these tests:

- STR-003 when the required method is absent from the component class.
- VAL-006 when the method's return annotation is present but wrong.
- NO finding when the annotation is missing entirely (principle 2: policy
  not correctness; the framework accepts unannotated method returns as
  long as the runtime value matches, and Pydantic validation downstream
  catches runtime mismatches).
- NO finding on the canonical scaffolded file (FP insurance against the
  B1 scaffolders drifting).
"""
from pathlib import Path
import textwrap

from echolon.strategy.validators.component_signatures import (
    validate_component_signatures,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


def _canonical_entry(tmp_path: Path) -> None:
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


def _canonical_exit(tmp_path: Path) -> None:
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


def _canonical_risk(tmp_path: Path) -> None:
    _write(tmp_path / "risk.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import RiskOutput

        class risk_manager(BaseComponent):
            def can_trade(self) -> RiskOutput:
                return RiskOutput(trading_allowed=True, risk_reason="x")
    ''')


def _canonical_sizer(tmp_path: Path) -> None:
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


def _canonical_all(tmp_path: Path) -> None:
    _canonical_entry(tmp_path)
    _canonical_exit(tmp_path)
    _canonical_risk(tmp_path)
    _canonical_sizer(tmp_path)


def test_canonical_correct_strategy_no_findings(tmp_path: Path):
    _canonical_all(tmp_path)
    report = validate_component_signatures(strategy_dir=tmp_path)
    assert not report.any_errors, report.findings


def test_missing_method_surfaces_STR_003(tmp_path: Path):
    _canonical_exit(tmp_path)
    _canonical_risk(tmp_path)
    _canonical_sizer(tmp_path)
    # entry.py: class declared but missing generate_signal method.
    _write(tmp_path / "entry.py", '''
        from echolon.strategy.component import BaseComponent

        class entry_rule(BaseComponent):
            def some_other_method(self):
                pass
    ''')

    report = validate_component_signatures(strategy_dir=tmp_path)
    codes = [f.code for f in report.findings]
    assert "STR-003" in codes
    finding = next(f for f in report.findings if f.code == "STR-003")
    assert finding.context.get("method") == "generate_signal"
    assert "entry" in finding.context.get("component", "") or finding.context.get("file", "").endswith("entry.py")


def test_wrong_return_annotation_surfaces_VAL_006(tmp_path: Path):
    _canonical_entry(tmp_path)
    _canonical_risk(tmp_path)
    _canonical_sizer(tmp_path)
    # exit.py: should_exit present but annotated -> dict instead of ExitSignalOutput.
    _write(tmp_path / "exit.py", '''
        from echolon.strategy.component import BaseComponent

        class exit_rule(BaseComponent):
            def should_exit(self) -> dict:
                return {}
    ''')

    report = validate_component_signatures(strategy_dir=tmp_path)
    codes = [f.code for f in report.findings]
    assert "VAL-006" in codes
    f = next(f for f in report.findings if f.code == "VAL-006")
    assert f.context.get("method") == "should_exit"
    assert f.context.get("expected_return") == "ExitSignalOutput"
    assert "dict" in f.context.get("actual_annotation", "")


def test_fp_insurance_missing_annotation_must_not_raise(tmp_path: Path):
    """Principle 2: policy vs correctness. An unannotated return is a
    stylistic choice, not a correctness violation. The method body is
    what determines the runtime schema; Pydantic validation catches
    actual mismatches downstream."""
    _canonical_exit(tmp_path)
    _canonical_risk(tmp_path)
    _canonical_sizer(tmp_path)
    _write(tmp_path / "entry.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import EntrySignalOutput

        class entry_rule(BaseComponent):
            # Intentionally unannotated — the framework accepts this.
            def generate_signal(self):
                return EntrySignalOutput(
                    signal="HOLD", strength=0.0, type="hold",
                    entry_reason="x", intent=None, regime="unknown",
                )
    ''')

    report = validate_component_signatures(strategy_dir=tmp_path)
    assert not report.any_errors, (
        f"FP insurance violated — missing annotation must NOT raise. "
        f"Got: {report.findings}"
    )


def test_each_component_checked_independently(tmp_path: Path):
    """Four distinct violations across four files — all surface in one
    report. Validators don't fail-fast."""
    # entry: missing method
    _write(tmp_path / "entry.py", '''
        from echolon.strategy.component import BaseComponent
        class entry_rule(BaseComponent): pass
    ''')
    # exit: wrong annotation
    _write(tmp_path / "exit.py", '''
        from echolon.strategy.component import BaseComponent
        class exit_rule(BaseComponent):
            def should_exit(self) -> dict: return {}
    ''')
    # risk: missing method
    _write(tmp_path / "risk.py", '''
        from echolon.strategy.component import BaseComponent
        class risk_manager(BaseComponent): pass
    ''')
    # sizer: wrong annotation
    _write(tmp_path / "sizer.py", '''
        from echolon.strategy.component import BaseComponent
        class position_sizer(BaseComponent):
            def calculate_size(self, entry_signal) -> list: return []
    ''')

    report = validate_component_signatures(strategy_dir=tmp_path)
    # Should see BOTH families surfaced (2 x STR-003 + 2 x VAL-006).
    codes = [f.code for f in report.findings]
    assert codes.count("STR-003") == 2
    assert codes.count("VAL-006") == 2


def test_missing_file_is_not_our_concern(tmp_path: Path):
    """This validator assumes file-presence is checked elsewhere (preflight
    STR-001). If a component file is absent entirely, we skip it silently
    rather than surfacing a duplicate STR-001."""
    _canonical_entry(tmp_path)
    # Intentionally omit exit.py, risk.py, sizer.py.

    report = validate_component_signatures(strategy_dir=tmp_path)
    # Only entry was present and correct — no findings.
    assert not report.any_errors, (
        f"Missing component files should be silently skipped, not surfaced. "
        f"Got: {report.findings}"
    )


def test_annotation_via_string_forward_reference_still_works(tmp_path: Path):
    """``def generate_signal(self) -> "EntrySignalOutput":`` — string-quoted
    forward reference is a legal Python annotation. Must match without
    raising VAL-006."""
    _canonical_exit(tmp_path)
    _canonical_risk(tmp_path)
    _canonical_sizer(tmp_path)
    _write(tmp_path / "entry.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.schemas import EntrySignalOutput

        class entry_rule(BaseComponent):
            def generate_signal(self) -> "EntrySignalOutput":
                return EntrySignalOutput(
                    signal="HOLD", strength=0.0, type="hold",
                    entry_reason="x", intent=None, regime="unknown",
                )
    ''')

    report = validate_component_signatures(strategy_dir=tmp_path)
    assert not report.any_errors, report.findings


def test_dotted_annotation_is_matched_by_last_segment(tmp_path: Path):
    """``-> schemas.EntrySignalOutput`` should match. We compare by the
    trailing identifier because echolon's imports are flexible."""
    _canonical_exit(tmp_path)
    _canonical_risk(tmp_path)
    _canonical_sizer(tmp_path)
    _write(tmp_path / "entry.py", '''
        from echolon.strategy.component import BaseComponent
        from echolon.strategy import schemas

        class entry_rule(BaseComponent):
            def generate_signal(self) -> schemas.EntrySignalOutput:
                return schemas.EntrySignalOutput(
                    signal="HOLD", strength=0.0, type="hold",
                    entry_reason="x", intent=None, regime="unknown",
                )
    ''')

    report = validate_component_signatures(strategy_dir=tmp_path)
    assert not report.any_errors, report.findings
