"""Induced-failure smoke test for the 6 new Part B1 error codes.

For each of VAL-003, VAL-005, VAL-006, PRM-003, PRM-004, BT-010:

1. Start from the known-clean aluminum_baseline canary fixture.
2. Inject a minimal, realistic bug that should trigger exactly this code.
3. Run the matching validator.
4. Assert the finding surfaces with the expected code.

Mirror of the WFA-001 induced-failure smoke test pattern — confirms
the catalog-validator wiring end-to-end, not the validator logic in
isolation (that's covered by the fine-grained unit tests under
test_<validator>.py).
"""
from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

import pytest


_FIXTURE_SRC = Path(__file__).parent.parent.parent / "fixtures" / "baselines" / "aluminum_baseline"


@pytest.fixture
def clean_strategy_dir(tmp_path: Path) -> Path:
    """Fresh copy of the known-clean canary baseline in ``tmp_path``.
    Each test mutates this independently; pytest's tmp_path per-test
    isolation means no cross-contamination."""
    if not _FIXTURE_SRC.exists():
        pytest.skip(f"canary fixture missing: {_FIXTURE_SRC}")
    dest = tmp_path / "strategy"
    shutil.copytree(_FIXTURE_SRC, dest)
    return dest


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


# ============================================================================
# VAL-003: required JSON key missing
# (raised by validate_debug_completion on artifact with missing top-level keys)
# ============================================================================


def test_induced_VAL_003_missing_json_key(tmp_path: Path):
    from echolon.strategy.validators.debug_completion import validate_debug_completion

    artifact = tmp_path / "selected_robust_trial.json"
    artifact.write_text(json.dumps({"trial_number": 42}))  # missing params, metrics

    log = tmp_path / "debug.log"
    log.write_text("STAGE 4 COMPLETE\nSTAGE 5 COMPLETE\nFINAL SUCCESS\n", encoding="utf-8")

    report = validate_debug_completion(artifact_path=artifact, log_path=log)
    codes = [f.code for f in report.findings]
    assert "VAL-003" in codes


# ============================================================================
# VAL-005: component method arity mismatch
# (raised by validate_component_integration — inject by changing sizer arity)
# ============================================================================


def test_induced_VAL_005_sizer_arity_mismatch(clean_strategy_dir: Path):
    from echolon.strategy.validators.component_integration import (
        validate_component_integration,
    )

    sizer = clean_strategy_dir / "sizer.py"
    src = _read(sizer)
    # Replace ``def calculate_size(self, signal_data: ...)`` with a 0-arity version.
    # Use a simple string-level substitution that survives the v6.1 file structure.
    assert "def calculate_size(self, signal_data: EntrySignalOutput) -> SizerOutput:" in src, (
        "fixture v6.1 sizer no longer has the expected signature"
    )
    new_src = src.replace(
        "def calculate_size(self, signal_data: EntrySignalOutput) -> SizerOutput:",
        "def calculate_size(self) -> SizerOutput:",
    )
    _write(sizer, new_src)

    report = validate_component_integration(strategy_dir=clean_strategy_dir)
    codes = [f.code for f in report.findings]
    assert "VAL-005" in codes


# ============================================================================
# VAL-006: wrong return-type annotation
# (raised by validate_component_signatures on annotation mismatch)
# ============================================================================


def test_induced_VAL_006_wrong_return_annotation(clean_strategy_dir: Path):
    from echolon.strategy.validators.component_signatures import (
        validate_component_signatures,
    )

    entry = clean_strategy_dir / "entry.py"
    src = _read(entry)
    # Entry's generate_signal currently has ``-> EntrySignalOutput``. Change it
    # to ``-> dict`` to trigger VAL-006.
    assert "def generate_signal(self) -> EntrySignalOutput:" in src
    new_src = src.replace(
        "def generate_signal(self) -> EntrySignalOutput:",
        "def generate_signal(self) -> dict:",
        1,
    )
    _write(entry, new_src)

    report = validate_component_signatures(strategy_dir=clean_strategy_dir)
    codes = [f.code for f in report.findings]
    assert "VAL-006" in codes


# ============================================================================
# PRM-003: hardcoded threshold literal
# (raised by validate_parameter_access on numeric literal in comparison)
# ============================================================================


def test_induced_PRM_003_hardcoded_threshold(clean_strategy_dir: Path):
    from echolon.strategy.validators.parameter_access import (
        validate_parameter_access,
    )

    # Append a new method with a hardcoded threshold to entry.py. Leave the
    # existing (canary-clean) code in place — this isolates the one injected
    # violation.
    entry = clean_strategy_dir / "entry.py"
    addition = textwrap.dedent("""

        # INDUCED-FAILURE-BLOCK (B1-10): must raise PRM-003
        def _induced_hardcoded_threshold(self):
            cci = self.get_indicator('cci_14')
            if cci > 42.5:   # hardcoded float not sourced from self.<param>
                return "LONG"
            return "HOLD"
    """)
    _write(entry, _read(entry) + addition)

    report = validate_parameter_access(strategy_dir=clean_strategy_dir)
    codes = [f.code for f in report.findings]
    assert "PRM-003" in codes


# ============================================================================
# PRM-004: defensive self.params.get()
# (raised by validate_parameter_access — and also validate_component_logging —
# on the .get() antipattern)
# ============================================================================


def test_induced_PRM_004_defensive_params_get(clean_strategy_dir: Path):
    from echolon.strategy.validators.parameter_access import (
        validate_parameter_access,
    )

    entry = clean_strategy_dir / "entry.py"
    addition = textwrap.dedent("""

        # INDUCED-FAILURE-BLOCK (B1-10): must raise PRM-004
        def _induced_defensive_get(self):
            threshold = self.params.get("cci_threshold", 100.0)
            return threshold
    """)
    _write(entry, _read(entry) + addition)

    report = validate_parameter_access(strategy_dir=clean_strategy_dir)
    codes = [f.code for f in report.findings]
    assert "PRM-004" in codes


# ============================================================================
# BT-010: required log marker absent
# (raised by validate_debug_completion)
# ============================================================================


def test_induced_BT_010_missing_log_marker(tmp_path: Path):
    from echolon.strategy.validators.debug_completion import validate_debug_completion

    artifact = tmp_path / "selected_robust_trial.json"
    artifact.write_text(json.dumps({
        "trial_number": 1, "params": {}, "metrics": {"sharpe_ratio": 1.0},
    }))
    log = tmp_path / "debug.log"
    log.write_text("STAGE 4 COMPLETE\n", encoding="utf-8")  # missing STAGE 5 + FINAL SUCCESS

    report = validate_debug_completion(artifact_path=artifact, log_path=log)
    codes = [f.code for f in report.findings]
    assert "BT-010" in codes


# ============================================================================
# Meta-check: every injected bug also round-trips cleanly through the
# catalog's raise_error() so downstream tools that materialize the code
# into an EchelonError get consistent surface.
# ============================================================================


@pytest.mark.parametrize("code", ["VAL-003", "VAL-005", "VAL-006", "PRM-003", "PRM-004", "BT-010"])
def test_new_code_raises_via_catalog(code: str):
    from echolon.errors import raise_error

    # Provide just enough context to satisfy each code's fix_template.
    ctx_per_code = {
        "VAL-003": {"file": "x", "missing_keys": [], "present_keys": []},
        "VAL-005": {"component": "x", "method": "y", "expected": "a", "actual": "b"},
        "VAL-006": {"component": "x", "method": "y", "expected_return": "A", "actual_annotation": "B"},
        "PRM-003": {"file": "x", "line": 1, "literal": "2", "suggestion": "z"},
        "PRM-004": {"file": "x", "line": 1, "call": "q"},
        "BT-010":  {"log_path": "x", "missing_marker": [], "last_marker_seen": None},
    }
    with pytest.raises(Exception) as exc_info:
        raise_error(code, **ctx_per_code[code])
    assert exc_info.value.code == code
