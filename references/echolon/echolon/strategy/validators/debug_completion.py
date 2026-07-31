"""Validate that debug-stage artifacts landed on disk as expected.

Deterministic three-check sweep:

1. ``STR-001`` — ``selected_robust_trial.json`` (or the custom
   ``artifact_path``) exists and the log file exists.
2. ``VAL-003`` — the JSON parses and carries every required top-level key.
3. ``BT-010`` — the log contains each required marker substring at
   least once (order irrelevant — an FP-insurance fixture in the test
   suite locks this).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from echolon.strategy.validators import Finding, Report


_DEFAULT_REQUIRED_JSON_KEYS: Sequence[str] = ("trial_number", "params", "metrics")
_DEFAULT_REQUIRED_LOG_MARKERS: Sequence[str] = (
    "STAGE 4 COMPLETE",
    "STAGE 5 COMPLETE",
    "FINAL SUCCESS",
)


def validate_debug_completion(
    artifact_path: "Path | str",
    log_path: "Path | str",
    required_json_keys: Iterable[str] = _DEFAULT_REQUIRED_JSON_KEYS,
    required_log_markers: Iterable[str] = _DEFAULT_REQUIRED_LOG_MARKERS,
) -> Report:
    """Return a ``Report`` with findings for every problem detected.

    Parameters
    ----------
    artifact_path
        Path to the JSON artifact (typically
        ``<workspace>/backtest/selected_robust_trial.json``).
    log_path
        Path to the debug log file.
    required_json_keys
        Top-level keys expected on the artifact JSON.
    required_log_markers
        Substrings expected somewhere in the log (order irrelevant).
    """
    report = Report()
    artifact_path = Path(artifact_path)
    log_path = Path(log_path)
    required_json_keys = tuple(required_json_keys)
    required_log_markers = tuple(required_log_markers)

    # --- Artifact existence + JSON shape ------------------------------------
    if not artifact_path.exists():
        report.add(Finding(
            code="STR-001",
            message=f"Required artifact missing: {artifact_path}",
            context={"file": str(artifact_path)},
        ))
    else:
        try:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            report.add(Finding(
                code="VAL-003",
                message=f"Artifact is not valid JSON: {e}",
                context={
                    "file": str(artifact_path),
                    "missing_keys": list(required_json_keys),
                    "present_keys": [],
                },
            ))
        else:
            missing = [k for k in required_json_keys if k not in payload]
            if missing:
                report.add(Finding(
                    code="VAL-003",
                    message=f"Artifact missing required keys: {missing}",
                    context={
                        "file": str(artifact_path),
                        "missing_keys": missing,
                        "present_keys": sorted(payload.keys()),
                    },
                ))

    # --- Log file existence + marker presence -------------------------------
    if not log_path.exists():
        report.add(Finding(
            code="STR-001",
            message=f"Log file missing: {log_path}",
            context={"file": str(log_path)},
        ))
    else:
        log_text = log_path.read_text(encoding="utf-8")
        missing_markers = [m for m in required_log_markers if m not in log_text]
        if missing_markers:
            last_seen: str | None = None
            for marker in required_log_markers:
                if marker in log_text:
                    last_seen = marker
            report.add(Finding(
                code="BT-010",
                message=f"Required log markers absent: {missing_markers}",
                context={
                    "log_path": str(log_path),
                    "missing_marker": missing_markers,
                    "last_marker_seen": last_seen,
                },
            ))

    return report
