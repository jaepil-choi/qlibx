"""Acceptance tests for validate_debug_completion.

Validates post-run artifacts: the selected_robust_trial.json exists and
has required keys; the debug log contains each required stage marker.

FP-insurance test (marker order doesn't matter) is the canary that
prevents this validator from rejecting legitimate reruns that landed
markers in a non-canonical sequence.
"""
import json
from pathlib import Path

from echolon.strategy.validators.debug_completion import validate_debug_completion


def _write_valid_artifact(path: Path) -> None:
    path.write_text(json.dumps({
        "trial_number": 42,
        "params": {"entry_rsi": 30, "exit_atr": 2.0},
        "metrics": {"sharpe_ratio": 1.2, "annual_return": 0.15, "max_drawdown_pct": 0.08},
    }), encoding="utf-8")


def _write_valid_log(path: Path) -> None:
    path.write_text("STAGE 4 COMPLETE\nSTAGE 5 COMPLETE\nFINAL SUCCESS\n", encoding="utf-8")


def test_canonical_correct_case_no_findings(tmp_path: Path):
    art = tmp_path / "selected_robust_trial.json"
    log = tmp_path / "debug.log"
    _write_valid_artifact(art)
    _write_valid_log(log)

    report = validate_debug_completion(artifact_path=art, log_path=log)
    assert not report.any_errors, report.findings


def test_missing_artifact_surfaces_STR_001(tmp_path: Path):
    art = tmp_path / "does_not_exist.json"
    log = tmp_path / "debug.log"
    _write_valid_log(log)

    report = validate_debug_completion(artifact_path=art, log_path=log)
    assert report.any_errors
    codes = [f.code for f in report.findings]
    assert "STR-001" in codes


def test_malformed_json_surfaces_VAL_003(tmp_path: Path):
    """Non-JSON bytes in the artifact — the validator must report VAL-003
    rather than crash."""
    art = tmp_path / "selected_robust_trial.json"
    art.write_text("this is not JSON {{{", encoding="utf-8")
    log = tmp_path / "debug.log"
    _write_valid_log(log)

    report = validate_debug_completion(artifact_path=art, log_path=log)
    codes = [f.code for f in report.findings]
    assert "VAL-003" in codes


def test_missing_required_key_surfaces_VAL_003(tmp_path: Path):
    art = tmp_path / "selected_robust_trial.json"
    art.write_text(json.dumps({"trial_number": 42}), encoding="utf-8")  # missing params, metrics
    log = tmp_path / "debug.log"
    _write_valid_log(log)

    report = validate_debug_completion(artifact_path=art, log_path=log)
    codes = [f.code for f in report.findings]
    assert "VAL-003" in codes
    # Must include which keys are missing in the finding context.
    val_finding = next(f for f in report.findings if f.code == "VAL-003")
    missing = val_finding.context.get("missing_keys")
    assert missing is not None
    assert "params" in missing and "metrics" in missing


def test_missing_log_marker_surfaces_BT_010(tmp_path: Path):
    art = tmp_path / "selected_robust_trial.json"
    _write_valid_artifact(art)
    log = tmp_path / "debug.log"
    # Only STAGE 4 present — STAGE 5 + FINAL SUCCESS missing.
    log.write_text("STAGE 4 COMPLETE\n", encoding="utf-8")

    report = validate_debug_completion(artifact_path=art, log_path=log)
    codes = [f.code for f in report.findings]
    assert "BT-010" in codes
    bt_finding = next(f for f in report.findings if f.code == "BT-010")
    assert "STAGE 5 COMPLETE" in bt_finding.context.get("missing_marker", [])
    assert "FINAL SUCCESS" in bt_finding.context.get("missing_marker", [])
    # Last seen marker should be included for diagnostic value.
    assert bt_finding.context.get("last_marker_seen") == "STAGE 4 COMPLETE"


def test_missing_log_file_surfaces_STR_001(tmp_path: Path):
    art = tmp_path / "selected_robust_trial.json"
    _write_valid_artifact(art)
    log = tmp_path / "missing.log"

    report = validate_debug_completion(artifact_path=art, log_path=log)
    codes = [f.code for f in report.findings]
    # Missing log file is also STR-001 (file-presence family).
    assert "STR-001" in codes


def test_fp_insurance_non_canonical_marker_order_still_passes(tmp_path: Path):
    """FP insurance: marker presence is the correctness rule, not order.

    A rerun of the producing pipeline might land markers in a different
    sequence (e.g., retry causes FINAL SUCCESS to appear before STAGE 5
    COMPLETE when the retry happens to succeed first). The validator
    must NOT raise on ordering — only on absence.
    """
    art = tmp_path / "selected_robust_trial.json"
    _write_valid_artifact(art)
    log = tmp_path / "debug.log"
    # Intentionally non-canonical order.
    log.write_text(
        "STAGE 4 COMPLETE\nFINAL SUCCESS\nSTAGE 5 COMPLETE\n",
        encoding="utf-8",
    )

    report = validate_debug_completion(artifact_path=art, log_path=log)
    assert not report.any_errors, (
        f"FP insurance violated — marker order must not matter. "
        f"Got findings: {report.findings}"
    )


def test_customizable_required_keys_and_markers(tmp_path: Path):
    """The validator accepts custom ``required_json_keys`` and
    ``required_log_markers`` so callers can tune for non-default artifacts."""
    art = tmp_path / "custom.json"
    art.write_text(json.dumps({"custom_key": "yes"}), encoding="utf-8")
    log = tmp_path / "custom.log"
    log.write_text("my_custom_marker appeared\n", encoding="utf-8")

    report = validate_debug_completion(
        artifact_path=art,
        log_path=log,
        required_json_keys=("custom_key",),
        required_log_markers=("my_custom_marker",),
    )
    assert not report.any_errors

    # Missing custom key now surfaces.
    art.write_text(json.dumps({}), encoding="utf-8")
    report = validate_debug_completion(
        artifact_path=art,
        log_path=log,
        required_json_keys=("custom_key",),
        required_log_markers=("my_custom_marker",),
    )
    assert any(f.code == "VAL-003" for f in report.findings)


def test_report_to_dict_round_trip_preserves_context(tmp_path: Path):
    art = tmp_path / "selected_robust_trial.json"
    art.write_text(json.dumps({"trial_number": 1}), encoding="utf-8")
    log = tmp_path / "debug.log"
    _write_valid_log(log)

    report = validate_debug_completion(artifact_path=art, log_path=log)
    d = report.to_dict()
    assert d["any_errors"] is True
    # Context dicts must JSON-serialize cleanly.
    import json as _json
    _json.dumps(d)  # no TypeError
